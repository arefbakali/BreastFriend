"""Génération de PDF de test (texte, scanné/image, vide, volumineux)."""
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

LOREM = ("Le suivi régulier permet de repérer tôt les effets indésirables des traitements. "
         "Les consultations sont l'occasion de poser toutes ses questions à l'équipe soignante. ")


def text_pdf(pages, header="Guide BreastFriend — document de test"):
    """pages : liste de (titre, [paragraphes]). En-tête et pied de page répétés (à nettoyer)."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    for i, (title, paras) in enumerate(pages, start=1):
        c.setFont("Helvetica", 8)
        c.drawString(50, h - 30, header)
        c.drawString(w - 90, 25, f"Page {i}")
        y = h - 70
        if title:
            c.setFont("Helvetica-Bold", 13)
            c.drawString(50, y, title)
            y -= 24
        c.setFont("Helvetica", 10)
        for para in paras:
            words, line = para.split(), ""
            for word in words:
                if c.stringWidth(line + " " + word, "Helvetica", 10) > w - 100:
                    c.drawString(50, y, line)
                    y -= 14
                    line = word
                else:
                    line = (line + " " + word).strip()
            c.drawString(50, y, line)
            y -= 22
        c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf(lines):
    """PDF sans couche texte : une image de page (comme un document scanné)."""
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    y = 150
    for ln in lines:
        d.text((110, y), ln, fill="black", font=font)
        y += 60
    buf = BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def blank_pdf(n=2):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(n):
        c.showPage()
    c.save()
    return buf.getvalue()


def large_pdf(n_pages=120):
    return text_pdf([(f"Chapitre {i}", [LOREM * 6, f"Point clé numéro {i} du protocole de suivi."])
                     for i in range(1, n_pages + 1)])
