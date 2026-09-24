import queue

from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context

import events
from auth import create_ticket, login_required
from database import dumps, execute, loads, query
from report import report_pdf
from services import ensure_checkin_notifications
from vision.wig_recommender import FACE_SHAPES, FaceNotFound, analyze_face, load_catalog, recommend

bp = Blueprint("common", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    # public : aucun détail de configuration (fournisseurs, modèles, URL) n'est exposé ici
    return jsonify(status="ok", rag=current_app.extensions["rag"].status()["state"])


@bp.post("/tickets")
@login_required()
def ticket():
    purpose = (request.get_json(silent=True) or {}).get("purpose")
    if purpose not in ("events", "pdf"):
        return jsonify(error="Usage de jeton inconnu."), 400
    return jsonify(ticket=create_ticket(g.user, purpose), expires_in=120)


@bp.get("/events")
@login_required(ticket="events")
def event_stream():
    """Flux Server-Sent Events de l'utilisatrice connectée."""
    sid, q = events.subscribe(g.user["id"], g.user["role"])

    def gen():
        try:
            yield "retry: 3000\nevent: ready\ndata: {}\n\n"
            while True:
                try:
                    name, payload = q.get(timeout=20)
                    yield f"event: {name}\ndata: {payload}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"          # garde la connexion ouverte (proxys)
        finally:
            events.unsubscribe(sid)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@bp.get("/notifications")
@login_required()
def notifications():
    if g.user["role"] == "doctor":
        ensure_checkin_notifications(g.user["id"])
    rows = query("SELECT * FROM notifications WHERE user_id = ? ORDER BY is_read, id DESC LIMIT 100", (g.user["id"],))
    unread = sum(1 for r in rows if not r["is_read"])
    return jsonify(notifications=rows, unread=unread)


@bp.post("/notifications/read")
@login_required()
def mark_read():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if ids:
        marks = ",".join("?" * len(ids))
        execute(f"UPDATE notifications SET is_read = 1 WHERE user_id = ? AND id IN ({marks})", (g.user["id"], *ids))
    else:
        execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (g.user["id"],))
    events.publish([g.user["id"]], "notification", {"read": True})   # synchronise les autres onglets
    return jsonify(ok=True)


@bp.get("/reports/<int:rid>/pdf")
@login_required(ticket="pdf")
def pdf(rid):
    r = query("SELECT r.*, d.full_name AS doctor_name FROM reports r LEFT JOIN users d ON d.id = r.doctor_id WHERE r.id = ?",
              (rid,), one=True)
    if not r or g.user["id"] not in (r["patient_id"], r["doctor_id"]):
        return jsonify(error="Compte rendu introuvable."), 404
    data = report_pdf(loads(r["report_json"]), r["doctor_name"], r["doctor_comment"])
    disposition = "attachment" if request.args.get("download") else "inline"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="compte-rendu-{rid}.pdf"'})


# ---- Perruques (vision par ordinateur) --------------------------------------
def _catalog():
    from vision.wig_assets import catalog_with_tryon
    from vision.wig_recommender import CATALOG_PATH
    return catalog_with_tryon(CATALOG_PATH, current_app.config["STATIC_DIR"])


@bp.get("/wigs/catalog")
@login_required()
def catalog():
    return jsonify(items=_catalog(), face_shapes=FACE_SHAPES)


@bp.post("/wigs/analyze")
@login_required()
def analyze():
    f = request.files.get("photo")
    if not f:
        return jsonify(error="Ajoutez une photo de votre visage."), 400
    prefs = loads(request.form.get("preferences"), {}) or {}
    try:
        analysis = analyze_face(f.read())
    except FaceNotFound as exc:
        return jsonify(error=str(exc)), 422
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    rec = recommend(analysis, prefs, catalog=_catalog())
    stored = {k: v for k, v in analysis.items() if k != "annotated_image"}
    aid = execute("INSERT INTO wig_analyses (user_id, analysis_json, preferences_json, recommendations_json) VALUES (?,?,?,?)",
                  (g.user["id"], dumps(stored), dumps(prefs), dumps(rec)))
    return jsonify(id=aid, analysis=analysis, recommendations=rec)


@bp.post("/wigs/recommend")
@login_required()
def rerank():
    """Recalcule les recommandations (préférences ou forme corrigée) sans renvoyer la photo."""
    d = request.get_json(silent=True) or {}
    row = query("SELECT * FROM wig_analyses WHERE id = ? AND user_id = ?", (d.get("analysis_id"), g.user["id"]), one=True)
    if not row:
        return jsonify(error="Analyse introuvable : envoyez d'abord une photo."), 404
    prefs = d.get("preferences") or {}
    if prefs.get("face_shape_override") and prefs["face_shape_override"] not in FACE_SHAPES:
        prefs.pop("face_shape_override")
    rec = recommend(loads(row["analysis_json"]), prefs, catalog=_catalog())
    execute("UPDATE wig_analyses SET preferences_json = ?, recommendations_json = ? WHERE id = ?",
            (dumps(prefs), dumps(rec), row["id"]))
    return jsonify(recommendations=rec)


@bp.get("/wigs/last")
@login_required()
def last_analysis():
    row = query("SELECT * FROM wig_analyses WHERE user_id = ? ORDER BY id DESC LIMIT 1", (g.user["id"],), one=True)
    if not row:
        return jsonify(analysis=None)
    return jsonify(id=row["id"], analysis=loads(row["analysis_json"]), preferences=loads(row["preferences_json"], {}),
                   recommendations=loads(row["recommendations_json"]), created_at=row["created_at"])
