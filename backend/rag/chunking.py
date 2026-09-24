"""Étape 3 : découpage structuré en passages (chunks).

On ne coupe pas à un nombre arbitraire de caractères :
  1. le texte est découpé en paragraphes puis en phrases, chaque unité gardant
     sa page et sa section (titre Markdown ou titre détecté dans le PDF) ;
  2. les unités sont empilées jusqu'à CHUNK_SIZE_TOKENS, sans jamais couper une
     phrase (une phrase trop longue est scindée sur les espaces en dernier recours) ;
  3. un changement de section ferme le passage courant (pas de mélange de sections) ;
  4. le passage suivant reprend les dernières phrases (CHUNK_OVERLAP_TOKENS)
     de la même section pour ne pas perdre le contexte à la frontière.
"""
import re
from dataclasses import dataclass, field

from .text_utils import count_tokens

_SENT = re.compile(r"(?<=[.!?…])\s+(?=[«\"(A-ZÀ-Ý0-9])")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_NUM_HEADING = re.compile(r"^(\d+(\.\d+){0,3}\.?|[IVX]+\.)\s+[A-ZÀ-Ý].{2,80}$")
MIN_FLUSH_TOKENS = 20   # un fragment plus court est rattaché à la section suivante


@dataclass
class Chunk:
    ordinal: int
    text: str
    section: str | None
    page_start: int | None
    page_end: int | None
    tokens: int
    pages: list = field(default_factory=list)


def _is_pdf_heading(line):
    if len(line) > 90 or len(line) < 3 or line.endswith((".", ",", ";", ":")):
        return False
    if _NUM_HEADING.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters) and len(line.split()) <= 10


def _split_long(sentence, max_tokens):
    words, out, cur = sentence.split(), [], []
    for w in words:
        cur.append(w)
        if count_tokens(" ".join(cur)) >= max_tokens:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def iter_units(pages, source_type, max_tokens):
    """Produit (texte, page, section) ; met à jour la section au fil des titres."""
    doc_title, section, h1 = None, None, None
    for page in pages:
        if not page.text:
            continue
        for para in re.split(r"\n\s*\n", page.text):
            lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
            body = []
            for ln in lines:
                m = _MD_HEADING.match(ln) if source_type == "md" else None
                if m:
                    level, title = len(m.group(1)), m.group(2).strip()
                    if level == 1:
                        doc_title = doc_title or title
                        h1, section = title, title
                    else:
                        section = title
                    continue
                if source_type == "pdf" and _is_pdf_heading(ln) and not body:
                    section = ln.title() if ln.isupper() else ln
                    continue
                body.append(ln)
            if not body:
                continue
            # listes : une puce = une unité ; sinon découpage en phrases
            is_list = sum(bool(re.match(r"^([-•*]|\d+[.)])\s", b)) for b in body) >= max(2, len(body) // 2)
            pieces = body if is_list else _SENT.split(" ".join(body))
            for sent in pieces:
                sent = sent.strip()
                if not sent:
                    continue
                parts = _split_long(sent, max_tokens) if count_tokens(sent) > max_tokens else [sent]
                for part in parts:
                    yield part, page.number, section or h1
    return doc_title


def chunk_pages(pages, source_type, size_tokens=700, overlap_tokens=100):
    chunks, cur = [], []            # cur : liste de (texte, page, section, tokens)

    def flush(keep_overlap):
        nonlocal cur
        if not cur:
            return
        text = "\n".join(u[0] for u in cur) if _looks_like_list(cur) else " ".join(u[0] for u in cur)
        pages_ = [u[1] for u in cur if u[1] is not None]
        sections = list(dict.fromkeys(u[2] for u in cur if u[2]))
        chunks.append(Chunk(len(chunks), text, " / ".join(sections) or None, min(pages_) if pages_ else None,
                            max(pages_) if pages_ else None, count_tokens(text), sorted(set(pages_))))
        if keep_overlap and overlap_tokens > 0:
            tail, total = [], 0
            for u in reversed(cur):
                if total + u[3] > overlap_tokens:
                    break
                tail.insert(0, u)
                total += u[3]
            cur = tail if len(tail) < len(cur) else []
        else:
            cur = []

    for text, page, section in iter_units(pages, source_type, size_tokens):
        tokens = count_tokens(text)
        if cur and section != cur[-1][2] and sum(u[3] for u in cur) >= MIN_FLUSH_TOKENS:
            flush(keep_overlap=False)
        if cur and sum(u[3] for u in cur) + tokens > size_tokens:
            flush(keep_overlap=True)
        cur.append((text, page, section, tokens))
    flush(keep_overlap=False)
    return chunks


def _looks_like_list(units):
    return sum(bool(re.match(r"^([-•*]|\d+[.)])\s", u[0])) for u in units) >= 2


def document_title(pages, source_type, fallback):
    if source_type == "md":
        for page in pages:
            m = re.search(r"^#\s+(.+)$", page.text, re.M)
            if m:
                return m.group(1).strip()
    return fallback
