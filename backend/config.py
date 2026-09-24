"""Configuration centralisée (variables d'environnement / fichier .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name, default=""):
    """Une variable présente mais vide dans .env (« QDRANT_PATH= ») vaut sa valeur par défaut."""
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _bool(name, default=False):
    return str(_env(name, default)).lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    return int(_env(name, default))


def _float(name, default):
    return float(_env(name, default))


class Config:
    SECRET_KEY = _env("SECRET_KEY", "dev-secret-change-me")
    TOKEN_MAX_AGE = _int("TOKEN_MAX_AGE", 60 * 60 * 24 * 7)  # 7 jours

    DATA_DIR = Path(_env("DATA_DIR", BASE_DIR / "data"))
    DATABASE_PATH = Path(_env("DATABASE_PATH", DATA_DIR / "breastfriend.db"))
    UPLOAD_DIR = DATA_DIR / "uploads"
    DOCUMENTS_DIR = DATA_DIR / "documents"          # documents du RAG déposés par les médecins
    CORPUS_DIR = BASE_DIR / "rag" / "corpus"        # corpus intégré (indexé au premier démarrage)
    REPORTS_DIR = DATA_DIR / "reports"
    STATIC_DIR = BASE_DIR / "static"
    FRONTEND_DIST = Path(_env("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))

    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 40) * 1024 * 1024
    MAX_PHOTO_BYTES = 12 * 1024 * 1024

    # --- Confidentialité ---------------------------------------------------------
    # LOCAL_ONLY=true : refuse tout fournisseur distant (LLM / embeddings). Aucune
    # donnée de patiente ne quitte la machine.
    LOCAL_ONLY = _bool("LOCAL_ONLY", False)

    # --- LLM ------------------------------------------------------------------------
    # none | openai | openai_compatible | ollama   (alias hérités : groq, mistral, custom)
    LLM_PROVIDER = _env("LLM_PROVIDER", "none").lower()
    OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
    OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_BASE_URL = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_BASE_URL = _env("LLM_BASE_URL", "")      # openai_compatible : vLLM, LM Studio, Groq...
    LLM_API_KEY = _env("LLM_API_KEY", "")
    LLM_MODEL = _env("LLM_MODEL", "")
    OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    OLLAMA_NUM_CTX = _int("OLLAMA_NUM_CTX", 8192)
    # Modèles « raisonnants » (qwen3, deepseek-r1…) : false = pas de phase de réflexion. Vide = non envoyé.
    OLLAMA_THINK = _env("OLLAMA_THINK", "").lower()
    # vide = paramètre non envoyé (les modèles de raisonnement OpenAI le refusent)
    LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "0.2").strip()
    LLM_MAX_OUTPUT_TOKENS = _int("LLM_MAX_OUTPUT_TOKENS", 900)
    LLM_TIMEOUT = _int("LLM_TIMEOUT", 120)
    LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 2)

    # --- RAG : embeddings ---------------------------------------------------------
    # local (sentence-transformers) | ollama | openai | hashing (tests uniquement)
    EMBEDDING_PROVIDER = _env("EMBEDDING_PROVIDER", "local").lower()
    EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "")    # défaut selon le fournisseur
    EMBEDDING_DEVICE = _env("EMBEDDING_DEVICE", "")  # cpu | cuda | vide = auto
    EMBEDDING_BATCH_SIZE = _int("EMBEDDING_BATCH_SIZE", 16)
    EMBEDDING_QUERY_PREFIX = _env("EMBEDDING_QUERY_PREFIX", "")
    EMBEDDING_DOCUMENT_PREFIX = _env("EMBEDDING_DOCUMENT_PREFIX", "")

    # --- RAG : base vectorielle ----------------------------------------------------
    VECTOR_DB = _env("VECTOR_DB", "qdrant").lower()    # qdrant | local
    QDRANT_URL = _env("QDRANT_URL", "")                         # vide = mode embarqué (QDRANT_PATH)
    QDRANT_API_KEY = _env("QDRANT_API_KEY", "")
    QDRANT_PATH = Path(_env("QDRANT_PATH", DATA_DIR / "qdrant"))
    QDRANT_COLLECTION_PREFIX = _env("QDRANT_COLLECTION_PREFIX", "breastfriend")

    # --- RAG : découpage, recherche, reranking --------------------------------------
    CHUNK_SIZE_TOKENS = _int("CHUNK_SIZE_TOKENS", 700)
    CHUNK_OVERLAP_TOKENS = _int("CHUNK_OVERLAP_TOKENS", 100)
    RAG_HYBRID = _bool("RAG_HYBRID", True)                 # vecteurs + BM25 fusionnés (RRF)
    RAG_RETRIEVAL_TOP_K = _int("RAG_RETRIEVAL_TOP_K", 20)   # candidats avant reranking
    RAG_FINAL_TOP_K = _int("RAG_FINAL_TOP_K", 6)            # passages envoyés au LLM
    RAG_MIN_VECTOR_SCORE = _float("RAG_MIN_VECTOR_SCORE", 0.35)
    RAG_MIN_RERANK_SCORE = _float("RAG_MIN_RERANK_SCORE", 0.15)
    RAG_CONTEXT_MAX_TOKENS = _int("RAG_CONTEXT_MAX_TOKENS", 3500)
    RERANKER_ENABLED = _bool("RERANKER_ENABLED", True)
    RERANKER_MODEL = _env("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    RERANKER_MAX_LENGTH = _int("RERANKER_MAX_LENGTH", 1024)
    RAG_DEBUG = _bool("RAG_DEBUG", False)                    # scores visibles dans l'interface médecin
    CHAT_HISTORY_TURNS = _int("CHAT_HISTORY_TURNS", 6)      # messages d'historique envoyés au LLM
    CHAT_HISTORY_MAX_CHARS = _int("CHAT_HISTORY_MAX_CHARS", 4000)

    # --- OCR (PDF scannés) ---------------------------------------------------------
    OCR_ENABLED = _bool("OCR_ENABLED", True)
    OCR_LANG = _env("OCR_LANG", "fra+eng")
    OCR_DPI = _int("OCR_DPI", 200)

    # Indexation automatique au démarrage (corpus intégré + documents à mettre à jour)
    RAG_AUTO_SYNC = _bool("RAG_AUTO_SYNC", True)

    SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", True)
    CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
