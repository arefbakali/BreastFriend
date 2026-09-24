"""Étape 1 : extraction du texte page par page (PDF, TXT, Markdown), OCR si besoin."""
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("breastfriend.rag.extract")

MIN_PAGE_CHARS = 40   # en dessous, une page PDF est considérée vide / scannée


@dataclass
class Page:
    number: int | None      # numéro de page (1-based) ; None pour TXT / Markdown
    text: str
    method: str             # text | ocr | empty


class ExtractionError(ValueError):
    pass


def _ocr_available():
    try:
        import pytesseract
        from pdf2image import convert_from_path  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_page(path, number, lang, dpi):
    import pytesseract
    from pdf2image import convert_from_path

    images = convert_from_path(str(path), dpi=dpi, first_page=number, last_page=number)
    if not images:
        return ""
    try:
        return pytesseract.image_to_string(images[0], lang=lang)
    except pytesseract.TesseractError:
        # langue absente (ex. pack « fra » non installé) : on retente avec l'anglais
        return pytesseract.image_to_string(images[0], lang="eng")


def extract_pdf(path, ocr=True, ocr_lang="fra+eng", ocr_dpi=200):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractionError("PDF protégé par mot de passe.") from exc
        raw_pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError(f"PDF illisible : {exc}") from exc

    can_ocr = ocr and _ocr_available()
    if ocr and not can_ocr:
        log.info("OCR indisponible (tesseract / poppler absents) pour %s", Path(path).name)
    pages = []
    for i, text in enumerate(raw_pages, start=1):
        if len(text.strip()) >= MIN_PAGE_CHARS:
            pages.append(Page(i, text, "text"))
            continue
        if can_ocr:
            try:
                ocr_text = _ocr_page(path, i, ocr_lang, ocr_dpi)
            except Exception as exc:  # une page OCR ratée ne bloque pas le document
                log.warning("OCR échoué page %s de %s : %s", i, Path(path).name, exc)
                ocr_text = ""
            if len(ocr_text.strip()) >= MIN_PAGE_CHARS:
                pages.append(Page(i, ocr_text, "ocr"))
                continue
        pages.append(Page(i, "", "empty"))
    return pages


def extract_text_file(path):
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return [Page(None, data.decode(enc), "text")]
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Encodage de texte non reconnu.")


def extract(path, source_type, **ocr_opts):
    if source_type == "pdf":
        return extract_pdf(path, **ocr_opts)
    if source_type in ("md", "txt"):
        return extract_text_file(path)
    raise ExtractionError(f"Type de document non pris en charge : {source_type}")


# ---- Étape 2 : nettoyage ------------------------------------------------------------
def _repeated_lines(pages):
    """Lignes présentes sur plus de la moitié des pages (en-têtes / pieds de page)."""
    if len(pages) < 4:
        return set()
    counter = Counter()
    for p in pages:
        lines = {re.sub(r"\d+", "#", ln.strip()) for ln in p.text.splitlines() if 0 < len(ln.strip()) < 90}
        counter.update(lines)
    return {ln for ln, n in counter.items() if n > len(pages) / 2}


def clean_text(text, drop=frozenset()):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").replace("\u00ad", "")
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", text)
    lines = []
    for ln in text.split("\n"):
        stripped = re.sub(r"[ \t]+", " ", ln).strip()
        if drop and re.sub(r"\d+", "#", stripped) in drop:
            continue
        if re.fullmatch(r"(page\s*)?\d+(\s*/\s*\d+)?", stripped, re.I):  # numéros de page isolés
            continue
        lines.append(stripped)
    text = "\n".join(lines)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # mots coupés en fin de ligne
    # ligne coupée au milieu d'une phrase : on recolle (sans toucher aux titres ni aux listes)
    text = re.sub(r"([^\n.:!?;])\n(?![\n#\-•*\d])(?=[a-zà-ÿ(,])", r"\1 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pages(pages):
    drop = _repeated_lines([p for p in pages if p.method != "empty"])
    return [Page(p.number, clean_text(p.text, drop), p.method) for p in pages]
