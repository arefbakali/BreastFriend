"""Fournisseurs LLM interchangeables. Le reste de l'application n'appelle que
generate() / stream() : changer de fournisseur ne demande qu'une modification du .env.

  openai             -> API OpenAI « Responses » (/v1/responses)           — données envoyées à OpenAI
  openai_compatible  -> tout serveur /v1/chat/completions : vLLM, LM Studio, llama.cpp, Groq, Mistral…
  ollama             -> API native Ollama (/api/chat), local
  none               -> aucun LLM (le chatbot renvoie alors une erreur explicite)
"""
import json
import logging
import threading

from flask import current_app, has_app_context

from rag.providers_common import ProviderBlocked, ProviderError, check_local_only, is_local_url, post_json  # noqa: F401

log = logging.getLogger("breastfriend.llm")

# Alias conservés pour les anciens fichiers .env
LEGACY = {
    "groq": ("openai_compatible", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "mistral": ("openai_compatible", "https://api.mistral.ai/v1", "mistral-small-latest"),
    "custom": ("openai_compatible", "", ""),
}


class LLMUnavailable(RuntimeError):
    """Le LLM configuré ne répond pas (message technique dans les logs)."""


class BaseLLM:
    name = "none"
    remote = False

    def __init__(self, model, timeout=120, retries=2, temperature=0.2, max_tokens=900):
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self.max_tokens = max_tokens

    def status(self):
        return {"enabled": True, "provider": self.name, "model": self.model, "data_leaves_device": self.remote}

    def _wrap(self, fn):
        try:
            return fn()
        except ProviderError as exc:
            log.error("LLM %s/%s indisponible : %s", self.name, self.model, exc)
            raise LLMUnavailable(str(exc)) from exc

    def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        return self._wrap(lambda: self._generate(messages, temperature, max_tokens, json_mode))

    def stream(self, messages, *, temperature=None, max_tokens=None):
        """Itérateur de fragments de texte."""
        try:
            yield from self._stream(messages, temperature, max_tokens)
        except ProviderError as exc:
            log.error("LLM %s/%s indisponible (stream) : %s", self.name, self.model, exc)
            raise LLMUnavailable(str(exc)) from exc

    def _temp(self, t):
        t = self.temperature if t is None else t
        return None if t in (None, "") else float(t)


def _sse_lines(response):
    for raw in response.iter_lines(decode_unicode=True):
        if raw and raw.startswith("data:"):
            yield raw[5:].strip()


class OpenAIResponsesLLM(BaseLLM):
    name = "openai"
    remote = True

    def __init__(self, model, api_key, base_url, **kw):
        super().__init__(model, **kw)
        if not api_key:
            raise ProviderError("LLM_PROVIDER=openai nécessite OPENAI_API_KEY dans backend/.env")
        self.url = base_url.rstrip("/") + "/responses"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _payload(self, messages, temperature, max_tokens, stream, json_mode=False):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload = {"model": self.model, "instructions": system or None,
                   "input": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"],
                   "max_output_tokens": max_tokens or self.max_tokens, "stream": stream, "store": False}
        t = self._temp(temperature)
        if t is not None:
            payload["temperature"] = t
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        return {k: v for k, v in payload.items() if v is not None}

    def _generate(self, messages, temperature, max_tokens, json_mode):
        data = post_json(self.url, self._payload(messages, temperature, max_tokens, False, json_mode),
                         self.headers, self.timeout, self.retries).json()
        texts = [c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                 for c in item.get("content", []) if c.get("type") == "output_text"]
        text = "".join(texts).strip()
        if not text:
            raise ProviderError(f"Réponse vide (statut {data.get('status')}).")
        return text

    def _stream(self, messages, temperature, max_tokens):
        r = post_json(self.url, self._payload(messages, temperature, max_tokens, True), self.headers,
                      self.timeout, self.retries, stream=True)
        with r:
            for line in _sse_lines(r):
                ev = json.loads(line)
                t = ev.get("type")
                if t == "response.output_text.delta":
                    yield ev.get("delta", "")
                elif t in ("response.failed", "error"):
                    err = ev.get("error") or ev.get("response", {}).get("error") or {}
                    raise ProviderError(f"Erreur OpenAI : {err.get('message', 'inconnue')}")
                elif t == "response.completed":
                    return


class OpenAICompatibleLLM(BaseLLM):
    name = "openai_compatible"

    def __init__(self, model, base_url, api_key="", **kw):
        super().__init__(model, **kw)
        if not base_url or not model:
            raise ProviderError("LLM_PROVIDER=openai_compatible nécessite LLM_BASE_URL et LLM_MODEL")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.remote = not is_local_url(base_url)

    def _payload(self, messages, temperature, max_tokens, stream, json_mode=False):
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens or self.max_tokens,
                   "stream": stream}
        t = self._temp(temperature)
        if t is not None:
            payload["temperature"] = t
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _generate(self, messages, temperature, max_tokens, json_mode):
        data = post_json(self.url, self._payload(messages, temperature, max_tokens, False, json_mode),
                         self.headers, self.timeout, self.retries).json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not text.strip():
            raise ProviderError("Réponse vide du serveur LLM.")
        return text.strip()

    def _stream(self, messages, temperature, max_tokens):
        r = post_json(self.url, self._payload(messages, temperature, max_tokens, True), self.headers,
                      self.timeout, self.retries, stream=True)
        with r:
            for line in _sse_lines(r):
                if line == "[DONE]":
                    return
                choice = (json.loads(line).get("choices") or [{}])[0]
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield delta


class OllamaLLM(BaseLLM):
    name = "ollama"

    def __init__(self, model, base_url, num_ctx=8192, think="", **kw):
        super().__init__(model, **kw)
        self.url = base_url.rstrip("/") + "/api/chat"
        self.num_ctx = num_ctx
        self.think = {"true": True, "false": False}.get(think)
        self.remote = not is_local_url(base_url)

    def _payload(self, messages, temperature, max_tokens, stream, json_mode=False):
        opts = {"num_ctx": self.num_ctx, "num_predict": max_tokens or self.max_tokens}
        t = self._temp(temperature)
        if t is not None:
            opts["temperature"] = t
        payload = {"model": self.model, "messages": messages, "stream": stream, "options": opts}
        if self.think is not None:
            payload["think"] = self.think
        if json_mode:
            payload["format"] = "json"
        return payload

    def _generate(self, messages, temperature, max_tokens, json_mode):
        data = post_json(self.url, self._payload(messages, temperature, max_tokens, False, json_mode),
                         timeout=self.timeout, retries=self.retries).json()
        text = (data.get("message") or {}).get("content", "")
        if not text.strip():
            raise ProviderError("Réponse vide d'Ollama.")
        return text.strip()

    def _stream(self, messages, temperature, max_tokens):
        r = post_json(self.url, self._payload(messages, temperature, max_tokens, True), timeout=self.timeout,
                      retries=self.retries, stream=True)
        with r:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise ProviderError(f"Erreur Ollama : {ev['error']}")
                piece = (ev.get("message") or {}).get("content")
                if piece:
                    yield piece
                if ev.get("done"):
                    return


_lock = threading.Lock()
_cache = {}


def _resolve(cfg):
    provider = (cfg.get("LLM_PROVIDER") or "none").lower()
    base, model = cfg.get("LLM_BASE_URL"), cfg.get("LLM_MODEL")
    if provider in LEGACY:
        provider, preset_base, preset_model = LEGACY[provider]
        base, model = base or preset_base, model or preset_model
    return provider, base, model


def get_provider(cfg=None):
    """Instance unique par configuration ; None si aucun LLM n'est configuré."""
    cfg = cfg or current_app.config
    provider, base, model = _resolve(cfg)
    if provider in ("", "none", "off"):
        return None
    key = (provider, base, model, cfg.get("OPENAI_MODEL"), cfg.get("OLLAMA_MODEL"), cfg.get("OLLAMA_BASE_URL"),
           cfg.get("OPENAI_BASE_URL"), bool(cfg.get("LOCAL_ONLY")), bool(cfg.get("OPENAI_API_KEY")),
           bool(cfg.get("LLM_API_KEY")))
    with _lock:
        if key in _cache:
            return _cache[key]
        common = dict(timeout=cfg.get("LLM_TIMEOUT", 120), retries=cfg.get("LLM_MAX_RETRIES", 2),
                      temperature=cfg.get("LLM_TEMPERATURE", "0.2"), max_tokens=cfg.get("LLM_MAX_OUTPUT_TOKENS", 900))
        if provider == "openai":
            check_local_only(cfg.get("LOCAL_ONLY"), cfg["OPENAI_BASE_URL"], "LLM")
            inst = OpenAIResponsesLLM(cfg["OPENAI_MODEL"], cfg.get("OPENAI_API_KEY"), cfg["OPENAI_BASE_URL"], **common)
        elif provider == "openai_compatible":
            check_local_only(cfg.get("LOCAL_ONLY"), base or "", "LLM")
            inst = OpenAICompatibleLLM(model, base, cfg.get("LLM_API_KEY"), **common)
        elif provider == "ollama":
            check_local_only(cfg.get("LOCAL_ONLY"), cfg["OLLAMA_BASE_URL"], "LLM")
            inst = OllamaLLM(cfg["OLLAMA_MODEL"], cfg["OLLAMA_BASE_URL"], cfg.get("OLLAMA_NUM_CTX", 8192),
                             cfg.get("OLLAMA_THINK", ""), **common)
        else:
            raise ProviderError(f"LLM_PROVIDER inconnu : {provider}")
        _cache[key] = inst
        return inst


def reset_cache():
    with _lock:
        _cache.clear()


# ---- API simple utilisée par le questionnaire et le compte rendu ---------------------
def _safe_provider():
    if not has_app_context():
        return None
    try:
        return get_provider()
    except ProviderError as exc:          # mauvaise configuration ou LOCAL_ONLY
        log.error("LLM non configurable : %s", exc)
        return None


def is_enabled():
    return _safe_provider() is not None


def status():
    try:
        p = get_provider()
    except ProviderBlocked as exc:
        return {"enabled": False, "provider": _resolve(current_app.config)[0], "model": None, "error": str(exc),
                "data_leaves_device": False}
    except ProviderError as exc:
        return {"enabled": False, "provider": _resolve(current_app.config)[0], "model": None,
                "error": f"Configuration LLM incomplète : {exc}", "data_leaves_device": False}
    if p is None:
        return {"enabled": False, "provider": "none", "model": None, "data_leaves_device": False}
    return p.status()


def chat(messages, temperature=0.3, max_tokens=900, json_mode=False):
    p = _safe_provider()
    if p is None:
        raise LLMUnavailable("Aucun LLM configuré.")
    return p.generate(messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
