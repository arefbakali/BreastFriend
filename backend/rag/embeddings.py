"""Étape 4 : embeddings. Abstraction de fournisseur, chargée UNE fois par processus.

  local    -> sentence-transformers (défaut : BAAI/bge-m3, multilingue, 1024 dim.)
  ollama   -> API /api/embed d'Ollama (ex. « ollama pull bge-m3 ») : local, sans PyTorch
  openai   -> API OpenAI /v1/embeddings (text-embedding-3-small par défaut) — DONNÉES ENVOYÉES À OPENAI
  hashing  -> embeddings lexicaux déterministes, UNIQUEMENT pour les tests automatisés
"""
import hashlib
import logging
import re
import threading

import numpy as np

from .providers_common import ProviderError, check_local_only, post_json
from .text_utils import fold

log = logging.getLogger("breastfriend.rag.embeddings")

DEFAULT_MODELS = {
    "local": "BAAI/bge-m3",
    "ollama": "bge-m3",
    "openai": "text-embedding-3-small",
    "hashing": "hashing-384",
}


class EmbeddingProvider:
    name = "base"
    remote = False

    def __init__(self, model, batch_size=16, query_prefix="", document_prefix=""):
        self.model = model
        self.batch_size = max(1, batch_size)
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self._dim = None

    @property
    def fingerprint(self):
        return f"{self.name}:{self.model}"

    @property
    def dim(self):
        if self._dim is None:
            self._dim = int(self.embed_queries(["dimension"]).shape[1])
        return self._dim

    def _embed(self, texts):
        raise NotImplementedError

    def _batched(self, texts, on_progress=None):
        out = []
        for i in range(0, len(texts), self.batch_size):
            out.append(self._embed(texts[i:i + self.batch_size]))
            if on_progress:
                on_progress(min(len(texts), i + self.batch_size), len(texts))
        vecs = np.vstack(out).astype(np.float32) if out else np.zeros((0, self.dim), np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-12, None)          # normalisé -> produit scalaire = cosinus

    def embed_documents(self, texts, on_progress=None):
        return self._batched([self.document_prefix + t for t in texts], on_progress)

    def embed_queries(self, texts):
        return self._batched([self.query_prefix + t for t in texts])

    def embed_query(self, text):
        return self.embed_queries([text])[0]


class SentenceTransformerEmbeddings(EmbeddingProvider):
    name = "local"

    def __init__(self, model, device=None, **kw):
        super().__init__(model, **kw)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ProviderError("EMBEDDING_PROVIDER=local nécessite : pip install -r requirements-local-ml.txt") from exc
        log.info("Chargement du modèle d'embedding %s (une seule fois)…", model)
        self._model = SentenceTransformer(model, device=device or None)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    def _embed(self, texts):
        return self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                  convert_to_numpy=True, show_progress_bar=False)


class OllamaEmbeddings(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model, base_url, timeout=120, local_only=False, **kw):
        super().__init__(model, **kw)
        check_local_only(local_only, base_url, "Service d'embeddings")
        self.url = base_url.rstrip("/") + "/api/embed"
        self.timeout = timeout

    def _embed(self, texts):
        r = post_json(self.url, {"model": self.model, "input": texts}, timeout=self.timeout)
        data = r.json().get("embeddings")
        if not data or len(data) != len(texts):
            raise ProviderError(f"Réponse d'embedding Ollama invalide (modèle « {self.model} » installé ?)")
        return np.asarray(data, dtype=np.float32)


class OpenAIEmbeddings(EmbeddingProvider):
    name = "openai"
    remote = True

    def __init__(self, model, api_key, base_url="https://api.openai.com/v1", timeout=60, local_only=False, **kw):
        super().__init__(model, **kw)
        check_local_only(local_only, base_url, "Service d'embeddings")
        if not api_key:
            raise ProviderError("EMBEDDING_PROVIDER=openai nécessite OPENAI_API_KEY dans backend/.env")
        self.url = base_url.rstrip("/") + "/embeddings"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout
        self.batch_size = max(self.batch_size, 64)

    def _embed(self, texts):
        r = post_json(self.url, {"model": self.model, "input": texts}, headers=self.headers, timeout=self.timeout)
        items = sorted(r.json().get("data", []), key=lambda d: d["index"])
        if len(items) != len(texts):
            raise ProviderError("Réponse d'embedding OpenAI incomplète.")
        return np.asarray([d["embedding"] for d in items], dtype=np.float32)


class HashingEmbeddings(EmbeddingProvider):
    """Vecteurs lexicaux (hachage de mots et de trigrammes). Pas sémantique : tests seulement."""
    name = "hashing"

    def __init__(self, model="hashing-384", dim=384, **kw):
        super().__init__(model, **kw)
        self._dim = dim

    def _embed(self, texts):
        out = np.zeros((len(texts), self._dim), np.float32)
        for row, text in enumerate(texts):
            words = re.findall(r"[a-z0-9]+", fold(text))
            feats = words + [w[i:i + 4] for w in words if len(w) > 4 for i in range(len(w) - 3)]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
                out[row, h % self._dim] += 1.0 if h & 1 else -1.0
        return out


_lock = threading.Lock()
_cache = {}


def get_embedder(cfg):
    """Instance unique par configuration (le modèle n'est jamais rechargé par requête)."""
    provider = cfg["EMBEDDING_PROVIDER"]
    model = cfg.get("EMBEDDING_MODEL") or DEFAULT_MODELS.get(provider, "")
    key = (provider, model, cfg.get("OLLAMA_BASE_URL"), cfg.get("OPENAI_BASE_URL"), cfg.get("LOCAL_ONLY"))
    with _lock:
        if key in _cache:
            return _cache[key]
        common = dict(batch_size=cfg.get("EMBEDDING_BATCH_SIZE", 16),
                      query_prefix=cfg.get("EMBEDDING_QUERY_PREFIX", ""),
                      document_prefix=cfg.get("EMBEDDING_DOCUMENT_PREFIX", ""))
        if provider == "local":
            emb = SentenceTransformerEmbeddings(model, device=cfg.get("EMBEDDING_DEVICE"), **common)
        elif provider == "ollama":
            emb = OllamaEmbeddings(model, cfg["OLLAMA_BASE_URL"], local_only=cfg.get("LOCAL_ONLY"), **common)
        elif provider == "openai":
            emb = OpenAIEmbeddings(model, cfg.get("OPENAI_API_KEY"), cfg.get("OPENAI_BASE_URL"),
                                   local_only=cfg.get("LOCAL_ONLY"), **common)
        elif provider == "hashing":
            emb = HashingEmbeddings(model, **common)
        else:
            raise ProviderError(f"EMBEDDING_PROVIDER inconnu : {provider}")
        _cache[key] = emb
        return emb


def reset_cache():
    with _lock:
        _cache.clear()
