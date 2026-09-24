import json
import logging
import tempfile
from pathlib import Path

from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context
from werkzeug.utils import secure_filename

import llm
from auth import login_required
from database import dumps, execute, loads, query
from rag import chat_service
from rag.service import ALLOWED, DuplicateDocument, RagNotReady

bp = Blueprint("chat", __name__, url_prefix="/api")
log = logging.getLogger("breastfriend.routes.chat")


def rag():
    return current_app.extensions["rag"]


def _history():
    n = current_app.config["CHAT_HISTORY_TURNS"]
    return query("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                 (g.user["id"], n))[::-1]


def _question():
    question = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not question:
        return None, (jsonify(error="Message vide."), 400)
    if len(question) > 2000:
        return None, (jsonify(error="Message trop long (2000 caractères maximum)."), 400)
    return question, None


def _public(result, debug):
    """Scores de recherche réservés au mode diagnostic des médecins."""
    sources = [{k: v for k, v in s.items() if debug or k != "scores"} for s in result.get("sources", [])]
    out = dict(result, sources=sources)
    if not debug:
        out.pop("retrieval", None)
    return out


def _debug():
    return g.user["role"] == "doctor" and (current_app.config["RAG_DEBUG"] or request.args.get("debug") == "1")


def _save(question, result):
    execute("INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)", (g.user["id"], "user", question))
    return execute("INSERT INTO chat_history (user_id, role, content, sources_json) VALUES (?,?,?,?)",
                   (g.user["id"], "assistant", result["answer"],
                    dumps({"sources": [{k: v for k, v in s.items() if k != "scores"} for s in result["sources"]],
                           "mode": result["mode"], "urgent": result["urgent"], "cited": result.get("cited", [])})))


@bp.post("/chat")
@login_required()
def chat():
    question, err = _question()
    if err:
        return err
    try:
        result = chat_service.answer(rag(), current_app.config, question, _history())
    except chat_service.ChatError as exc:
        return jsonify(error=str(exc), urgent=exc.urgent), exc.status
    mid = _save(question, result)
    return jsonify(id=mid, **_public(result, _debug()))


@bp.post("/chat/stream")
@login_required()
def chat_stream():
    """Réponse progressive (NDJSON : une ligne JSON par événement)."""
    question, err = _question()
    if err:
        return err
    history, debug, cfg = _history(), _debug(), current_app.config

    def gen():
        try:
            for ev in chat_service.stream(rag(), cfg, question, history):
                if ev["type"] == "done":
                    ev["id"] = _save(question, ev)
                    ev = _public(ev, debug)
                elif ev["type"] == "sources":
                    ev = _public(ev, debug)
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except chat_service.ChatError as exc:
            yield json.dumps({"type": "error", "error": str(exc), "urgent": exc.urgent}, ensure_ascii=False) + "\n"
        except Exception:
            log.exception("Erreur pendant la génération")
            yield json.dumps({"type": "error", "error": "Erreur interne pendant la génération."}) + "\n"

    return Response(stream_with_context(gen()), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.get("/chat/history")
@login_required()
def history():
    rows = query("SELECT * FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 60", (g.user["id"],))[::-1]
    out = []
    for r in rows:
        meta = loads(r.get("sources_json"), {}) or {}
        out.append({"id": r["id"], "role": r["role"], "content": r["content"], "sources": meta.get("sources", []),
                    "mode": meta.get("mode"), "urgent": meta.get("urgent", False), "cited": meta.get("cited", []),
                    "created_at": r["created_at"]})
    return jsonify(messages=out)


@bp.delete("/chat/history")
@login_required()
def clear_history():
    execute("DELETE FROM chat_history WHERE user_id = ?", (g.user["id"],))
    return jsonify(ok=True)


@bp.get("/rag/status")
@login_required()
def rag_status():
    s = rag().status()
    if g.user["role"] != "doctor":        # les patientes n'ont besoin que de l'essentiel
        s = {k: s[k] for k in ("state", "ready_documents", "chunks")}
    return jsonify(llm=llm.status(), rag=s)


# ---- Base de connaissances (médecins) ----------------------------------------------
@bp.get("/rag/search")
@login_required(roles="doctor")
def rag_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify(results=[], retrieval={})
    try:
        passages, info = rag().search(q, final_k=min(int(request.args.get("k", 6)), 20))
    except RagNotReady as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(results=[p.to_dict() for p in passages], retrieval=info)


@bp.get("/rag/documents")
@login_required(roles="doctor")
def list_documents():
    return jsonify(documents=rag().list_documents(), status=rag().status(),
                   allowed=sorted(ALLOWED), max_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024))


@bp.get("/rag/documents/<doc_id>")
@login_required(roles="doctor")
def document_detail(doc_id):
    doc = rag().get(doc_id)
    if not doc:
        return jsonify(error="Document introuvable."), 404
    return jsonify(document=doc, chunks=rag().chunks_of(doc_id))


@bp.post("/rag/documents")
@login_required(roles="doctor")
def upload_document():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="Aucun fichier reçu."), 400
    name = secure_filename(f.filename) or "document"
    if Path(name).suffix.lower() not in ALLOWED:
        return jsonify(error="Formats acceptés : PDF, Markdown (.md), texte (.txt)."), 400
    tmp_dir = current_app.config["DOCUMENTS_DIR"] / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmp_dir, suffix=Path(name).suffix.lower())
    with open(fd, "wb") as out:
        f.save(out)
    try:
        doc = rag().register_file(Path(tmp), name, g.user["id"])
    except DuplicateDocument as exc:
        Path(tmp).unlink(missing_ok=True)
        return jsonify(error=f"Ce document est déjà dans la base (« {exc.document['filename']} »).",
                       document=exc.document), 409
    except ValueError as exc:
        Path(tmp).unlink(missing_ok=True)
        return jsonify(error=str(exc)), 400
    return jsonify(document=doc), 202          # indexation en arrière-plan


@bp.post("/rag/documents/<doc_id>/reindex")
@login_required(roles="doctor")
def reindex_document(doc_id):
    doc = rag().reindex(doc_id)
    if not doc:
        return jsonify(error="Document introuvable."), 404
    return jsonify(document=doc), 202


@bp.delete("/rag/documents/<doc_id>")
@login_required(roles="doctor")
def delete_document(doc_id):
    try:
        if not rag().delete(doc_id):
            return jsonify(error="Document introuvable."), 404
    except RagNotReady as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(ok=True)
