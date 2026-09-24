"""Chatbot RAG : question -> recherche -> contexte -> LLM -> réponse citée.

Pas de repli extractif : si le LLM est indisponible, l'utilisatrice reçoit une erreur
claire (et, pour une question urgente, la consigne d'urgence), jamais un faux texte.
"""
import logging
import re

import llm

from .context import build_context
from .prompts import DISCLAIMER, NO_CONTEXT_MESSAGE, URGENT_PREFIX, build_messages
from .service import RagNotReady
from .text_utils import fold

log = logging.getLogger("breastfriend.chat")

URGENT_PATTERNS = [
    r"fi[eè]vre", r"\b3[89]([,.]\d)? ?°?c?\b", r"du mal a respirer", r"difficult\w* a respirer", r"essouffl",
    r"douleur (a la |dans la )?poitrine", r"douleur thoracique", r"saign\w* (beaucoup|abondant|important)",
    r"hemorragie", r"malaise", r"evanoui", r"confusion", r"suicid", r"en finir", r"me tuer", r"envie de mourir",
]
SMALL_TALK = [
    (r"^(bonjour|bonsoir|salut|coucou|hello|hi|salam|aslema|ahla)\b",
     "Bonjour, je suis BreastFriend. Je réponds à vos questions sur l'autopalpation, le dépistage, les traitements "
     "du cancer du sein, leurs effets secondaires, le choix d'une perruque ou le soutien émotionnel, à partir des "
     "documents validés de l'application. Que souhaitez-vous savoir ?"),
    (r"^(merci|thanks|chokran|y3aychek)\b", "Avec plaisir. Je reste là si vous avez d'autres questions. Prenez soin de vous."),
]
FOLLOW_UP = re.compile(r"^(et|mais|alors|ensuite|apres|aussi|donc|pourquoi|comment ca)\b|\b(ca|cela|celui|celle|ce traitement|"
                       r"cette|ces effets|il|elle|ils|elles|le meme)\b")
_CITE = re.compile(r"\[(\d{1,2})\]")


class ChatError(Exception):
    def __init__(self, message, status=503, urgent=False):
        super().__init__(message)
        self.status = status
        self.urgent = urgent


def is_urgent(text):
    t = fold(text)
    return any(re.search(p, t) for p in URGENT_PATTERNS)


def trim_history(history, turns, max_chars):
    """Derniers échanges seulement, marques de citation retirées (elles renvoyaient à d'anciennes sources)."""
    out, total = [], 0
    for h in reversed([h for h in history if h.get("role") in ("user", "assistant") and h.get("content")][-turns:]):
        content = _CITE.sub("", h["content"]).replace(f"_{DISCLAIMER}_", "").strip()[:1500]
        if total + len(content) > max_chars:
            break
        out.insert(0, {"role": h["role"], "content": content})
        total += len(content)
    return out


def retrieval_query(question, history):
    """L'historique aide à comprendre une relance (« Et après la chimio ? ») mais ne remplace
    jamais la recherche : on l'ajoute seulement à la requête de recherche."""
    q = fold(question)
    if len(q.split()) <= 6 or FOLLOW_UP.search(q):
        previous = next((h["content"] for h in reversed(history) if h.get("role") == "user"), None)
        if previous:
            return f"{previous[:300]} {question}"
    return question


def validate_citations(text, sources):
    valid = {s["n"] for s in sources}
    cited = sorted({int(n) for n in _CITE.findall(text) if int(n) in valid})
    cleaned = _CITE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
    return cleaned, cited


def _small_talk(question):
    q = fold(question)
    for pattern, reply in SMALL_TALK:
        if re.match(pattern, q) and len(q.split()) <= 4:
            return reply
    return None


def prepare(rag, cfg, question, history):
    """-> dict avec 'direct' (réponse sans LLM : salutation / aucune source) ou 'messages' pour le LLM."""
    urgent = is_urgent(question)
    reply = _small_talk(question)
    if reply:
        return {"direct": reply, "mode": "smalltalk", "sources": [], "urgent": False, "retrieval": {}}
    hist = trim_history(history, cfg["CHAT_HISTORY_TURNS"], cfg["CHAT_HISTORY_MAX_CHARS"])
    try:
        passages, info = rag.search(retrieval_query(question, hist))
    except RagNotReady as exc:
        raise ChatError(f"{exc} Réessayez dans quelques instants.", 503, urgent) from exc
    if not passages:
        return {"direct": (URGENT_PREFIX if urgent else "") + NO_CONTEXT_MESSAGE, "mode": "no_context",
                "sources": [], "urgent": urgent, "retrieval": info}
    context, sources = build_context(passages, cfg["RAG_CONTEXT_MAX_TOKENS"])
    return {"messages": build_messages(question, context, hist), "sources": sources, "urgent": urgent,
            "retrieval": info}


def _provider(cfg):
    try:
        provider = llm.get_provider(cfg)
    except llm.ProviderError as exc:
        log.error("Configuration LLM invalide : %s", exc)
        raise ChatError("L'assistante n'est pas correctement configurée (modèle de langage). "
                        "Prévenez l'administrateur.", 503) from exc
    if provider is None:
        raise ChatError("Aucun modèle de langage n'est configuré sur ce serveur (LLM_PROVIDER). "
                        "L'assistante ne peut pas répondre.", 503)
    return provider


def _finish(text, prep, provider):
    text, cited = validate_citations(text.strip(), prep["sources"])
    prefix = URGENT_PREFIX if prep["urgent"] and "190" not in text[:300] else ""
    return {"answer": f"{prefix}{text}\n\n_{DISCLAIMER}_", "sources": prep["sources"], "cited": cited,
            "grounded": bool(cited), "mode": "llm", "provider": provider.name, "model": provider.model,
            "urgent": prep["urgent"], "retrieval": prep["retrieval"]}


def _unavailable(prep_urgent):
    msg = ("L'assistante est momentanément indisponible : le modèle de langage ne répond pas. "
           "Réessayez dans un instant.")
    if prep_urgent:
        msg = URGENT_PREFIX + msg
    return ChatError(msg, 503, prep_urgent)


def answer(rag, cfg, question, history):
    prep = prepare(rag, cfg, question, history)
    if "direct" in prep:
        return {"answer": prep["direct"], "sources": [], "cited": [], "grounded": prep["mode"] != "no_context",
                "mode": prep["mode"], "urgent": prep["urgent"], "retrieval": prep["retrieval"]}
    provider = _provider(cfg)
    try:
        text = provider.generate(prep["messages"])
    except llm.LLMUnavailable as exc:
        raise _unavailable(prep["urgent"]) from exc
    return _finish(text, prep, provider)


def stream(rag, cfg, question, history):
    """Générateur d'événements : sources -> delta* -> done  (ou error)."""
    prep = prepare(rag, cfg, question, history)
    if "direct" in prep:
        yield {"type": "done", "answer": prep["direct"], "sources": [], "cited": [], "mode": prep["mode"],
               "urgent": prep["urgent"], "grounded": prep["mode"] != "no_context"}
        return
    provider = _provider(cfg)
    yield {"type": "sources", "sources": prep["sources"], "urgent": prep["urgent"]}
    parts = []
    try:
        for piece in provider.stream(prep["messages"]):
            parts.append(piece)
            yield {"type": "delta", "text": piece}
    except llm.LLMUnavailable as exc:
        raise _unavailable(prep["urgent"]) from exc
    if not "".join(parts).strip():
        raise _unavailable(prep["urgent"])
    yield dict(_finish("".join(parts), prep, provider), type="done")
