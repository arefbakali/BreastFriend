"""Éléments communs aux fournisseurs distants : session HTTP réutilisée, retries,
contrôle du mode LOCAL_ONLY."""
import logging
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("breastfriend.providers")
_session_lock = threading.Lock()
_session = None

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal", "ollama", "vllm"}


class ProviderError(RuntimeError):
    """Erreur technique d'un fournisseur (réseau, quota, modèle absent...)."""

    def __init__(self, message, retryable=False, status=None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class ProviderBlocked(ProviderError):
    """Fournisseur distant refusé parce que LOCAL_ONLY=true."""


def http():
    """Session requests partagée (keep-alive : pas de nouvelle connexion TLS par appel)."""
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            _session.headers["User-Agent"] = "BreastFriend/2.0"
        return _session


def is_local_url(url):
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".local") or host.startswith(("192.168.", "10.", "172."))


def check_local_only(local_only, url, what):
    if local_only and not is_local_url(url):
        raise ProviderBlocked(f"{what} distant refusé : LOCAL_ONLY=true (URL {urlparse(url).hostname}).")


def post_json(url, payload, headers=None, timeout=60, retries=2, stream=False):
    """POST JSON avec retries exponentiels sur erreurs réseau / 429 / 5xx."""
    last = None
    for attempt in range(retries + 1):
        try:
            r = http().post(url, json=payload, headers=headers or {}, timeout=timeout, stream=stream)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = ProviderError(f"Connexion impossible à {urlparse(url).netloc} : {exc.__class__.__name__}",
                                 retryable=True)
        else:
            if r.status_code < 400:
                return r
            detail = r.text[:300]
            retryable = r.status_code in (408, 409, 429) or r.status_code >= 500
            last = ProviderError(f"HTTP {r.status_code} de {urlparse(url).netloc} : {detail}",
                                 retryable=retryable, status=r.status_code)
            r.close()
        if not last.retryable or attempt == retries:
            break
        delay = min(8.0, 0.6 * (2 ** attempt))
        log.warning("Tentative %s/%s échouée (%s) — nouvel essai dans %.1fs", attempt + 1, retries + 1, last, delay)
        time.sleep(delay)
    raise last
