"""Service RAG : registre des documents, pipeline d'ingestion en arrière-plan, recherche.

    fichier -> extraction (page par page, OCR si besoin) -> nettoyage -> découpage
            -> embeddings (une seule fois) -> base vectorielle + index BM25 -> « ready »

Les modèles (embeddings, reranker) et la connexion à la base vectorielle sont chargés
une fois, en arrière-plan au démarrage, puis réutilisés par toutes les requêtes.
"""
import hashlib
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import events
from database import session

from . import keyword_index
from .chunking import chunk_pages, document_title
from .embeddings import get_embedder
from .extraction import ExtractionError, _ocr_available, clean_pages, extract
from .reranker import get_reranker
from .retrieval import retrieve
from .vectorstore import get_store

log = logging.getLogger("breastfriend.rag")

ALLOWED = {".pdf": "pdf", ".md": "md", ".markdown": "md", ".txt": "txt"}
PIPELINE_VERSION = "2"
# signatures de fichier (ne jamais se fier seulement à l'extension)
PDF_MAGIC = b"%PDF-"


class DuplicateDocument(Exception):
    def __init__(self, document):
        super().__init__("Document déjà présent")
        self.document = document


class RagNotReady(RuntimeError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class RagService:
    def __init__(self, app, jobs):
        self.cfg = app.config
        self.jobs = jobs
        self.db_path = app.config["DATABASE_PATH"]
        self.docs_dir = Path(app.config["DOCUMENTS_DIR"])
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self._ready = threading.Event()
        self._init_error = None
        self._titles = {}
        self.embedder = self.store = self.reranker = None

    # ---- initialisation (arrière-plan) -------------------------------------------------
    def start(self, sync=True):
        threading.Thread(target=self._init, args=(sync,), name="bf-rag-init", daemon=True).start()

    def _init(self, sync):
        t0 = time.perf_counter()
        try:
            self.embedder = get_embedder(self.cfg)
            self.store = get_store(self.cfg, self.embedder)
            self.reranker = get_reranker(self.cfg)
            self._init_error = None
            self._ready.set()
            log.info("RAG prêt en %.1fs (embeddings %s, base %s, reranker %s)", time.perf_counter() - t0,
                     self.embedder.fingerprint, self.store.backend, getattr(self.reranker, "model", None))
            if sync:
                self.sync()
        except Exception as exc:
            self._init_error = str(exc)
            log.exception("Initialisation du RAG impossible")
        finally:
            events.publish_role("doctor", "rag_status", self.status())

    def wait_ready(self, timeout=None):
        if not self._ready.wait(timeout):
            if self._init_error:
                raise RagNotReady(self._init_error)
            raise RagNotReady("Le moteur de recherche démarre (chargement des modèles)…")
        return True

    @property
    def fingerprint(self):
        return (f"{self.embedder.fingerprint}|{self.store.backend}|c{self.cfg['CHUNK_SIZE_TOKENS']}"
                f"o{self.cfg['CHUNK_OVERLAP_TOKENS']}|p{PIPELINE_VERSION}")

    def status(self):
        with session(self.db_path) as conn:
            rows = conn.execute("SELECT status, COUNT(*), COALESCE(SUM(chunks),0) FROM rag_documents "
                                "WHERE status != 'deleted' GROUP BY status").fetchall()
        by = {r[0]: r[1] for r in rows}
        return {
            "state": "ready" if self._ready.is_set() else ("error" if self._init_error else "loading"),
            "error": self._init_error,
            "embedding": {"provider": self.cfg["EMBEDDING_PROVIDER"], "model": getattr(self.embedder, "model", None),
                          "remote": bool(getattr(self.embedder, "remote", False))},
            "vector_db": self.cfg["VECTOR_DB"],
            "reranker": getattr(self.reranker, "model", None) if getattr(self.reranker, "enabled", False) else None,
            "hybrid": bool(self.cfg["RAG_HYBRID"]),
            "documents": sum(by.values()), "ready_documents": by.get("ready", 0),
            "chunks": sum(r[2] for r in rows if r[0] == "ready"), "by_status": by,
        }

    # ---- registre -------------------------------------------------------------------
    def _set(self, doc_id, notify=True, **fields):
        fields.setdefault("progress", None)
        if fields["progress"] is None:
            fields.pop("progress")
        cols = ", ".join(f"{k} = ?" for k in fields)
        with session(self.db_path) as conn:
            conn.execute(f"UPDATE rag_documents SET {cols} WHERE id = ?", (*fields.values(), doc_id))
        if notify:
            doc = self.get(doc_id)
            if doc:
                events.publish_role("doctor", "rag_document", doc)

    def get(self, doc_id):
        with session(self.db_path) as conn:
            r = conn.execute("SELECT * FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(r) if r else None

    def list_documents(self):
        with session(self.db_path) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM rag_documents WHERE status != 'deleted' "
                                                  "ORDER BY origin DESC, created_at DESC")]

    def register_file(self, tmp_path, filename, user_id=None, origin="upload", keep_path=False):
        """Enregistre un fichier (déjà écrit sur disque) et lance son indexation."""
        ext = Path(filename).suffix.lower()
        source_type = ALLOWED.get(ext)
        if not source_type:
            raise ValueError("Formats acceptés : PDF, Markdown (.md), texte (.txt).")
        if source_type == "pdf":
            with open(tmp_path, "rb") as f:
                if not f.read(1024).lstrip().startswith(PDF_MAGIC):
                    raise ValueError("Ce fichier n'est pas un PDF valide.")
        checksum = sha256_file(tmp_path)
        with session(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM rag_documents WHERE checksum = ?", (checksum,)).fetchone()
        if existing and existing["status"] == "deleted":
            # document supprimé puis déposé à nouveau : on le réactive
            with session(self.db_path) as conn:
                conn.execute("UPDATE rag_documents SET status = 'uploaded', progress = 0, error = NULL, "
                             "uploaded_by = COALESCE(?, uploaded_by) WHERE id = ?", (user_id, existing["id"]))
            if origin == "upload" and not keep_path:
                Path(tmp_path).unlink(missing_ok=True)
            self.enqueue(existing["id"])
            return self.get(existing["id"])
        if existing:
            raise DuplicateDocument(dict(existing))
        doc_id = uuid.uuid4().hex
        if keep_path:
            stored = str(Path(tmp_path))
        else:
            dest = self.docs_dir / f"{doc_id}{ext}"
            shutil.move(str(tmp_path), dest)
            stored = str(dest.relative_to(self.cfg["DATA_DIR"]))
        with session(self.db_path) as conn:
            conn.execute("INSERT INTO rag_documents (id, filename, stored_path, source_type, origin, checksum, size_bytes, "
                         "uploaded_by, status) VALUES (?,?,?,?,?,?,?,?, 'uploaded')",
                         (doc_id, filename, stored, source_type, origin, checksum, Path(self._abs(stored)).stat().st_size,
                          user_id))
        events.publish_role("doctor", "rag_document", self.get(doc_id))
        self.enqueue(doc_id)
        return self.get(doc_id)

    def _abs(self, stored):
        p = Path(stored)
        return p if p.is_absolute() else Path(self.cfg["DATA_DIR"]) / p

    def enqueue(self, doc_id):
        return self.jobs.submit(doc_id, self.process, doc_id)

    # ---- pipeline d'ingestion (thread d'arrière-plan) ---------------------------------------
    def process(self, doc_id):
        doc = self.get(doc_id)
        if not doc:
            return
        t0 = time.perf_counter()
        try:
            self.wait_ready(timeout=600)
            self._set(doc_id, status="processing", progress=0.05, error=None)
            path = self._abs(doc["stored_path"])
            if not path.exists():
                raise ExtractionError("Fichier source introuvable sur le disque.")
            pages = clean_pages(extract(path, doc["source_type"], ocr=self.cfg["OCR_ENABLED"],
                                        ocr_lang=self.cfg["OCR_LANG"], ocr_dpi=self.cfg["OCR_DPI"]))
            ocr_pages = sum(p.method == "ocr" for p in pages)
            empty_pages = sum(p.method == "empty" for p in pages)
            n_pages = len(pages) if doc["source_type"] == "pdf" else None
            self._set(doc_id, notify=False, pages=n_pages, ocr_pages=ocr_pages, empty_pages=empty_pages)
            chunks = chunk_pages(pages, doc["source_type"], self.cfg["CHUNK_SIZE_TOKENS"], self.cfg["CHUNK_OVERLAP_TOKENS"])
            if not chunks:
                if doc["source_type"] != "pdf":
                    reason = "document vide"
                elif not self.cfg["OCR_ENABLED"]:
                    reason = "aucune page ne contient de texte ; PDF scanné ? activez l'OCR (OCR_ENABLED=true)"
                elif not _ocr_available():
                    reason = "aucune page ne contient de texte ; PDF scanné ? installez Tesseract et Poppler pour l'OCR"
                else:
                    reason = "aucune page ne contient de texte lisible, même après OCR"
                raise ExtractionError(f"Rien à indexer — {reason}.")
            title = document_title(pages, doc["source_type"], Path(doc["filename"]).stem.replace("_", " "))
            self._set(doc_id, status="embedding", progress=0.15, pages=n_pages, ocr_pages=ocr_pages,
                      empty_pages=empty_pages)

            texts = [f"{title} — {c.section}\n{c.text}" if c.section else f"{title}\n{c.text}" for c in chunks]
            last = [0.0]

            def progress(done, total):
                frac = 0.15 + 0.7 * done / total
                if frac - last[0] >= 0.05 or done == total:     # limite les écritures / événements
                    last[0] = frac
                    self._set(doc_id, progress=round(frac, 3))

            vectors = self.embedder.embed_documents(texts, on_progress=progress)
            self._set(doc_id, status="indexing", progress=0.9)
            ids = [f"{doc_id}:{c.ordinal}" for c in chunks]
            # remplace atomiquement l'ancienne version (réindexation)
            self.store.delete_document(doc_id)
            self.store.upsert([(cid, vec, {"document_id": doc_id, "filename": doc["filename"], "section": c.section,
                                           "page_start": c.page_start, "page_end": c.page_end, "ordinal": c.ordinal,
                                           "source_type": doc["source_type"], "uploaded_at": doc["created_at"]})
                               for cid, vec, c in zip(ids, vectors, chunks)])
            with session(self.db_path) as conn:
                keyword_index.delete_document(conn, doc_id)
                conn.execute("DELETE FROM rag_chunks WHERE document_id = ?", (doc_id,))
                conn.executemany("INSERT INTO rag_chunks (id, document_id, ordinal, text, section, page_start, page_end, tokens) "
                                 "VALUES (?,?,?,?,?,?,?,?)",
                                 [(cid, doc_id, c.ordinal, c.text, c.section, c.page_start, c.page_end, c.tokens)
                                  for cid, c in zip(ids, chunks)])
                keyword_index.index_chunks(conn, [(cid, c.section or "", c.text) for cid, c in zip(ids, chunks)])
            self._titles[doc_id] = title
            self._set(doc_id, status="ready", progress=1.0, chunks=len(chunks), index_fingerprint=self.fingerprint, title=title,
                      indexed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), error=None)
            log.info("Document %s indexé : %s passages en %.1fs", doc["filename"], len(chunks), time.perf_counter() - t0)
        except Exception as exc:
            msg = str(exc) if isinstance(exc, (ExtractionError, ValueError)) else f"{exc.__class__.__name__} : {exc}"
            log.exception("Indexation échouée pour %s", doc["filename"])
            self._set(doc_id, status="failed", error=msg[:500])

    # ---- opérations ------------------------------------------------------------------
    def reindex(self, doc_id):
        if not self.get(doc_id):
            return None
        self._set(doc_id, status="uploaded", progress=0.0, error=None)
        self.enqueue(doc_id)
        return self.get(doc_id)

    def delete(self, doc_id):
        doc = self.get(doc_id)
        if not doc:
            return False
        self.wait_ready(timeout=30)
        self.store.delete_document(doc_id)
        with session(self.db_path) as conn:
            keyword_index.delete_document(conn, doc_id)
            conn.execute("DELETE FROM rag_chunks WHERE document_id = ?", (doc_id,))
            if doc["origin"] == "builtin":
                # on garde une trace (checksum) pour qu'il ne soit pas réimporté au prochain démarrage
                conn.execute("UPDATE rag_documents SET status = 'deleted', chunks = 0 WHERE id = ?", (doc_id,))
            else:
                conn.execute("DELETE FROM rag_documents WHERE id = ?", (doc_id,))
        if doc["origin"] == "upload":
            self._abs(doc["stored_path"]).unlink(missing_ok=True)
        events.publish_role("doctor", "rag_document", {"id": doc_id, "deleted": True})
        return True

    def chunks_of(self, doc_id, limit=200):
        with session(self.db_path) as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, ordinal, section, page_start, page_end, tokens, substr(text, 1, 400) AS preview "
                "FROM rag_chunks WHERE document_id = ? ORDER BY ordinal LIMIT ?", (doc_id, limit))]

    def sync(self):
        """Au démarrage : indexe le corpus intégré s'il est nouveau et réindexe uniquement les
        documents dont l'empreinte (modèle, découpage) a changé. Rien n'est refait sinon."""
        corpus = Path(self.cfg["CORPUS_DIR"])
        self._migrate_legacy_uploads()
        with session(self.db_path) as conn:
            known = {r[0] for r in conn.execute("SELECT checksum FROM rag_documents")}
        for path in sorted(corpus.glob("*")) if corpus.exists() else []:
            if path.suffix.lower() in ALLOWED and sha256_file(path) not in known:
                try:
                    self.register_file(path, path.name, origin="builtin", keep_path=True)
                except DuplicateDocument:
                    pass
        stale = []
        with session(self.db_path) as conn:
            for r in conn.execute("SELECT id, status, index_fingerprint FROM rag_documents"):
                if r[1] in ("uploaded", "processing", "embedding", "indexing") or \
                        (r[1] == "ready" and r[2] != self.fingerprint):
                    stale.append(r[0])
        # un document « ready » dont les vecteurs ont disparu (base vectorielle effacée) est réindexé
        present = self.store.document_ids()
        with session(self.db_path) as conn:
            stale += [r[0] for r in conn.execute("SELECT id FROM rag_documents WHERE status = 'ready'")
                      if r[0] not in present and r[0] not in stale]
        for doc_id in stale:
            self.enqueue(doc_id)
        log.info("Synchronisation RAG : %s document(s) à (ré)indexer", len(stale))
        return stale

    def _migrate_legacy_uploads(self):
        """Documents déposés avec l'ancienne version (data/corpus_uploads, index TF-IDF) :
        copiés dans le nouveau registre une seule fois, puis indexés."""
        legacy = Path(self.cfg["DATA_DIR"]) / "corpus_uploads"
        if not legacy.is_dir():
            return
        for path in sorted(legacy.iterdir()):
            if path.suffix.lower() not in ALLOWED:
                continue
            tmp = self.docs_dir / f"legacy-{uuid.uuid4().hex}{path.suffix.lower()}"
            shutil.copy2(path, tmp)
            try:
                self.register_file(tmp, path.name, origin="upload")
                log.info("Document hérité migré : %s", path.name)
            except DuplicateDocument:
                tmp.unlink(missing_ok=True)
            except ValueError as exc:
                tmp.unlink(missing_ok=True)
                log.warning("Document hérité ignoré %s : %s", path.name, exc)

    # ---- recherche ---------------------------------------------------------------------
    def titles(self):
        if not self._titles:
            with session(self.db_path) as conn:
                self._titles = {r[0]: r[1] or r[2] for r in conn.execute("SELECT id, title, filename FROM rag_documents")}
        return self._titles

    def search(self, query, **kw):
        self.wait_ready(timeout=kw.pop("timeout", 30))
        with session(self.db_path) as conn:
            return retrieve(conn, self.cfg, self.embedder, self.store, self.reranker, query, titles=self.titles(), **kw)
