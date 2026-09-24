"""Étape 8 : construction du contexte. Uniquement les passages retenus, numérotés,
avec document et page, dans un budget de tokens. Le texte des documents est encadré
comme DONNÉES (balises <source>) pour que le modèle ne l'interprète pas comme des
instructions (injection de prompt via un PDF déposé)."""
import re

from .text_utils import count_tokens


def page_label(page_start, page_end):
    if page_start is None:
        return None
    return f"{page_start}" if page_start == page_end or page_end is None else f"{page_start}–{page_end}"


def _sanitize(text):
    # un document ne peut pas fermer la balise de données ni simuler un nouveau bloc SOURCE
    text = re.sub(r"</?\s*source[^>]*>", "", text, flags=re.I)
    return re.sub(r"\[\s*SOURCE\s+\d+\s*\]", "[source]", text, flags=re.I)


def build_context(passages, max_tokens=3500):
    """-> (texte du contexte, sources numérotées). Les passages sont déjà triés par pertinence."""
    blocks, sources, used = [], [], 0
    for p in passages:
        n = len(sources) + 1
        page = page_label(p.page_start, p.page_end)
        header = f"[SOURCE {n}]\nDocument : {p.filename}\n" + (f"Page : {page}\n" if page else "") + \
                 (f"Section : {p.section}\n" if p.section else "")
        body = _sanitize(p.text)
        cost = count_tokens(header) + count_tokens(body)
        if used + cost > max_tokens:
            if sources:
                break
            body = body[: max(200, int(len(body) * (max_tokens - used) / cost))]   # au moins une source
        blocks.append(f"{header}Contenu :\n<source id=\"{n}\">\n{body}\n</source>")
        used += cost
        sources.append({"n": n, "document_id": p.document_id, "filename": p.filename, "title": p.title,
                        "page": page, "page_start": p.page_start, "page_end": p.page_end, "section": p.section,
                        "chunk_id": p.chunk_id, "excerpt": p.text[:420] + ("…" if len(p.text) > 420 else ""),
                        "scores": p.scores})
    return "\n\n".join(blocks), sources
