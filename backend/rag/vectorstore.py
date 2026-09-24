"""Étape 5 : base vectorielle.

  qdrant -> Qdrant (serveur Docker via QDRANT_URL, ou mode embarqué persistant via QDRANT_PATH)
  local  -> fichier SQLite + recherche exacte NumPy (petits corpus, tests, dépannage sans Qdrant)

Une collection est dédiée à chaque modèle d'embedding (nom + dimension) : changer de
modèle ne mélange jamais des vecteurs incompatibles.
"""
import logging
import re
import sqlite3
import threading
import uuid

import numpy as np

log = logging.getLogger("breastfriend.rag.vectors")
_NS = uuid.UUID("7b0e5c1e-6d38-4c5e-9d0a-5b2f3a9e1c11")


def collection_name(prefix, fingerprint, dim):
    slug = re.sub(r"[^a-z0-9]+", "-", fingerprint.lower()).strip("-")
    return f"{prefix}__{slug}__{dim}"


class VectorStore:
    backend = "base"

    def upsert(self, items):
        """items : [(chunk_id, vector, payload)] ; payload contient document_id."""
        raise NotImplementedError

    def delete_document(self, document_id):
        raise NotImplementedError

    def search(self, vector, k):
        """-> [(chunk_id, score, payload)] triés par score décroissant."""
        raise NotImplementedError

    def count(self, document_id=None):
        raise NotImplementedError

    def document_ids(self):
        raise NotImplementedError


class QdrantStore(VectorStore):
    backend = "qdrant"

    def __init__(self, name, dim, url="", api_key="", path=None):
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise RuntimeError("VECTOR_DB=qdrant nécessite : pip install qdrant-client") from exc
        self.models = models
        self.name, self.dim = name, dim
        if url:
            self.client = QdrantClient(url=url, api_key=api_key or None, timeout=30)
            self.location = url
        else:
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))   # embarqué, persistant sur disque
            self.location = str(path)
        if not self.client.collection_exists(name):
            self.client.create_collection(
                name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
            try:
                self.client.create_payload_index(name, "document_id", models.PayloadSchemaType.KEYWORD)
            except Exception as exc:  # le mode embarqué ignore les index de payload
                log.debug("Index de payload non créé : %s", exc)
        self._lock = threading.Lock()   # le mode embarqué n'est pas sûr en accès concurrent

    def _doc_filter(self, document_id):
        m = self.models
        return m.Filter(must=[m.FieldCondition(key="document_id", match=m.MatchValue(value=document_id))])

    def upsert(self, items):
        points = [self.models.PointStruct(id=str(uuid.uuid5(_NS, cid)), vector=vec.tolist(),
                                          payload=dict(payload, chunk_id=cid)) for cid, vec, payload in items]
        with self._lock:
            for i in range(0, len(points), 128):
                self.client.upsert(self.name, points=points[i:i + 128], wait=True)

    def delete_document(self, document_id):
        with self._lock:
            self.client.delete(self.name, points_selector=self.models.FilterSelector(
                filter=self._doc_filter(document_id)), wait=True)

    def search(self, vector, k):
        with self._lock:
            res = self.client.query_points(self.name, query=vector.tolist(), limit=k, with_payload=True)
        return [(p.payload["chunk_id"], float(p.score), p.payload) for p in res.points]

    def count(self, document_id=None):
        with self._lock:
            flt = self._doc_filter(document_id) if document_id else None
            return self.client.count(self.name, count_filter=flt, exact=True).count

    def document_ids(self):
        ids, offset = set(), None
        with self._lock:
            while True:
                points, offset = self.client.scroll(self.name, limit=512, offset=offset, with_payload=["document_id"],
                                                    with_vectors=False)
                ids.update(p.payload.get("document_id") for p in points)
                if offset is None:
                    return ids


class LocalStore(VectorStore):
    """Persistance SQLite ; matrice gardée en mémoire et mise à jour incrémentalement."""
    backend = "local"

    def __init__(self, name, dim, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.name, self.dim, self.location = name, dim, str(path)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(f'CREATE TABLE IF NOT EXISTS "{name}" (chunk_id TEXT PRIMARY KEY, document_id TEXT, '
                         'vector BLOB NOT NULL, payload TEXT)')
        self._db.execute(f'CREATE INDEX IF NOT EXISTS "ix_{name}_doc" ON "{name}"(document_id)')
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        import json
        rows = self._db.execute(f'SELECT chunk_id, vector, payload FROM "{self.name}"').fetchall()
        self.ids = [r[0] for r in rows]
        self.payloads = [json.loads(r[2]) for r in rows]
        self.matrix = (np.vstack([np.frombuffer(r[1], np.float32) for r in rows])
                       if rows else np.zeros((0, self.dim), np.float32))

    def upsert(self, items):
        import json
        with self._lock:
            self._db.executemany(
                f'INSERT OR REPLACE INTO "{self.name}" VALUES (?,?,?,?)',
                [(cid, p["document_id"], np.asarray(v, np.float32).tobytes(), json.dumps(dict(p, chunk_id=cid)))
                 for cid, v, p in items])
            self._db.commit()
            self._load()

    def delete_document(self, document_id):
        with self._lock:
            self._db.execute(f'DELETE FROM "{self.name}" WHERE document_id = ?', (document_id,))
            self._db.commit()
            self._load()

    def search(self, vector, k):
        with self._lock:
            if not self.ids:
                return []
            scores = self.matrix @ np.asarray(vector, np.float32)
            order = np.argsort(-scores)[:k]
            return [(self.ids[i], float(scores[i]), self.payloads[i]) for i in order]

    def count(self, document_id=None):
        with self._lock:
            if document_id is None:
                return len(self.ids)
            return sum(1 for p in self.payloads if p["document_id"] == document_id)

    def document_ids(self):
        with self._lock:
            return {p["document_id"] for p in self.payloads}


_lock = threading.Lock()
_stores = {}


def get_store(cfg, embedder):
    """Connexion unique et réutilisée par (backend, collection)."""
    name = collection_name(cfg["QDRANT_COLLECTION_PREFIX"], embedder.fingerprint, embedder.dim)
    key = (cfg["VECTOR_DB"], name, cfg.get("QDRANT_URL"), str(cfg.get("QDRANT_PATH")), str(cfg["DATA_DIR"]))
    with _lock:
        if key not in _stores:
            if cfg["VECTOR_DB"] == "qdrant":
                _stores[key] = QdrantStore(name, embedder.dim, cfg.get("QDRANT_URL"), cfg.get("QDRANT_API_KEY"),
                                           cfg.get("QDRANT_PATH"))
            elif cfg["VECTOR_DB"] == "local":
                _stores[key] = LocalStore(name, embedder.dim, cfg["DATA_DIR"] / "vectors.db")
            else:
                raise RuntimeError(f"VECTOR_DB inconnu : {cfg['VECTOR_DB']}")
            log.info("Base vectorielle %s prête : collection %s", cfg["VECTOR_DB"], name)
        return _stores[key]


def reset_cache():
    with _lock:
        _stores.clear()
