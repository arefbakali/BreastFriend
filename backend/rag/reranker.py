"""Étape 6 : reranking par cross-encodeur (défaut : BAAI/bge-reranker-v2-m3, multilingue).

Le cross-encodeur lit la question ET le passage ensemble : bien plus précis que la
similarité vectorielle, mais plus coûteux -> appliqué seulement aux ~20 candidats.
RERANKER_ENABLED=false le désactive (machines lentes) : l'ordre de fusion est conservé.
"""
import logging
import threading

import numpy as np

log = logging.getLogger("breastfriend.rag.reranker")


class NoReranker:
    enabled = False
    model = None

    def score(self, query, texts):
        return None


class CrossEncoderReranker:
    enabled = True

    def __init__(self, model, max_length=1024, device=None):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("RERANKER_ENABLED=true nécessite : pip install -r requirements-local-ml.txt "
                               "(ou RERANKER_ENABLED=false)") from exc
        log.info("Chargement du reranker %s (une seule fois)…", model)
        self.model = model
        self._ce = CrossEncoder(model, max_length=max_length, device=device or None)
        self._lock = threading.Lock()

    def score(self, query, texts):
        if not texts:
            return np.zeros(0)
        with self._lock:
            logits = self._ce.predict([(query, t) for t in texts], convert_to_numpy=True, show_progress_bar=False)
        logits = np.asarray(logits, dtype=np.float64).reshape(len(texts), -1)[:, -1]
        return 1.0 / (1.0 + np.exp(-logits))            # probabilité de pertinence 0..1


_lock = threading.Lock()
_cache = {}


def get_reranker(cfg):
    if not cfg.get("RERANKER_ENABLED"):
        return NoReranker()
    key = (cfg["RERANKER_MODEL"], cfg.get("RERANKER_MAX_LENGTH"))
    with _lock:
        if key not in _cache:
            _cache[key] = CrossEncoderReranker(cfg["RERANKER_MODEL"], cfg.get("RERANKER_MAX_LENGTH", 1024),
                                               cfg.get("EMBEDDING_DEVICE"))
        return _cache[key]


def register(cfg, reranker):
    """Permet d'injecter un reranker (tests)."""
    with _lock:
        _cache[(cfg["RERANKER_MODEL"], cfg.get("RERANKER_MAX_LENGTH"))] = reranker


def reset_cache():
    with _lock:
        _cache.clear()
