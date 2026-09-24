"""Génération du compte rendu médical structuré (JSON) et de sa version PDF."""
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import llm
from questionnaire import CATEGORIES, TRIAGE_LABELS

# Sections du rapport (reprend la structure du prototype du hackathon)
SECTIONS = [
    ("Observation", ["size_shape"]),
    ("Douleur", ["pain"]),
    ("Modifications cutanées", ["skin"]),
    ("Masses / boules", ["lump"]),
    ("Écoulement mamelonnaire", ["nipple_discharge"]),
    ("Aspect du mamelon", ["nipple_change"]),
    ("Antécédents familiaux", ["family_history"]),
    ("Autopalpation", ["self_exam"]),
    ("Sensibilité", ["tenderness"]),
    ("Ganglions lymphatiques", ["lymph"]),
    ("Tolérance du traitement", ["fever", "fatigue", "arm_swelling", "scar", "bone_pain"]),
    ("Bien-être émotionnel", ["mood"]),
]

VALUE_TXT = {"yes": "Oui", "no": "Non", "unknown": "Incertain"}

RECOMMENDATIONS = {
    "urgent": [
        "Contacter la patiente dans la journée.",
        "Avancer la consultation et envisager un bilan d'imagerie (mammographie / échographie) selon l'examen clinique.",
    ],
    "a_surveiller": [
        "Proposer une consultation ou avancer le prochain rendez-vous.",
        "Vérifier à l'examen clinique les éléments signalés par la patiente.",
    ],
    "rassurant": [
        "Poursuivre le suivi habituel et l'autopalpation mensuelle.",
    ],
}


def _finding(q, a):
    value = a.get("value", "unknown")
    detail = (a.get("detail") or "").strip()
    txt = f"{VALUE_TXT[value]} — {q['text']}"
    if detail:
        txt += f" Précision de la patiente : « {detail} »."
    return {"question": q["text"], "value": value, "detail": detail, "text": txt}


def _template_summary(patient_name, tri):
    if not tri["flags"]:
        s = (f"{patient_name} ne signale aucun symptôme d'alerte lors de ce questionnaire post-autopalpation. ")
    else:
        items = ", ".join(f["label"].lower() for f in tri["flags"])
        s = f"{patient_name} signale les éléments suivants : {items}. "
    s += f"Niveau de vigilance calculé : {TRIAGE_LABELS[tri['level']].lower()} (score {tri['score']}). "
    if tri["notes"]:
        s += " ".join(tri["notes"])
    return s.strip()


def build_report(patient, questions, answers, tri):
    by_cat = {}
    for q in questions:
        by_cat.setdefault(q["category"], []).append(_finding(q, answers.get(q["id"], {})))

    sections = []
    used = set()
    for title, cats in SECTIONS:
        findings = [f for c in cats for f in by_cat.get(c, [])]
        used.update(cats)
        if findings:
            sections.append({"title": title, "findings": findings,
                             "alert": any(f["value"] == "yes" and CATEGORIES.get(c, {}).get("weight", 0) >= 2
                                          and not CATEGORIES.get(c, {}).get("invert")
                                          for c in cats for f in by_cat.get(c, []))})
    others = [f for c, fs in by_cat.items() if c not in used for f in fs]
    if others:
        sections.append({"title": "Autres", "findings": others, "alert": False})

    name = patient.get("full_name", "La patiente")
    summary, generated_by = _template_summary(name, tri), "rules"
    if llm.is_enabled():
        facts = "\n".join(f"- {f['text']}" for s in sections for f in s["findings"])
        try:
            summary = llm.chat([
                {"role": "system", "content": "Tu es un assistant médical qui rédige des synthèses factuelles pour un oncologue. "
                                              "Pas de diagnostic, pas de spéculation, 4 phrases maximum, en français."},
                {"role": "user", "content": f"Patiente : {name}. Niveau de vigilance calculé : {TRIAGE_LABELS[tri['level']]} "
                                            f"(score {tri['score']}).\nRéponses :\n{facts}\n\nRédige la synthèse clinique."},
            ], temperature=0.1, max_tokens=300)
            generated_by = "llm"
        except llm.LLMUnavailable:
            pass

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "patient": {"id": patient.get("id"), "name": name},
        "triage": {"level": tri["level"], "label": TRIAGE_LABELS[tri["level"]], "score": tri["score"],
                   "flags": tri["flags"], "notes": tri["notes"]},
        "summary": summary,
        "sections": sections,
        "recommendations": RECOMMENDATIONS[tri["level"]],
        "generated_by": generated_by,
        "disclaimer": "Compte rendu généré automatiquement à partir des déclarations de la patiente. "
                      "Il ne constitue pas un diagnostic et doit être interprété par un professionnel de santé.",
    }


PINK = colors.HexColor("#C2185B")
TRIAGE_COLORS = {"rassurant": "#2E7D5B", "a_surveiller": "#C77700", "urgent": "#B3261E"}


def report_pdf(report, doctor_name=None, doctor_comment=None):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.6 * cm,
                            bottomMargin=1.6 * cm, title="Compte rendu BreastFriend")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=PINK, fontSize=20, spaceAfter=4, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], textColor=PINK, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#666666"))

    tri = report["triage"]
    color = TRIAGE_COLORS.get(tri["level"], "#333333")
    story = [
        Paragraph("BreastFriend — Compte rendu post-autopalpation", h1),
        Paragraph(f"Patiente : <b>{report['patient']['name']}</b> &nbsp;&nbsp; Date : {report['generated_at']}"
                  + (f" &nbsp;&nbsp; Médecin : {doctor_name}" if doctor_name else ""), body),
        Spacer(1, 6),
        Paragraph(f"<font color='{color}'><b>Niveau de vigilance : {tri['label']}</b></font> (score {tri['score']})", body),
        Paragraph("Synthèse", h2),
        Paragraph(report["summary"], body),
        Paragraph("Détail par section", h2),
    ]
    rows = [[Paragraph("<b>Section</b>", body), Paragraph("<b>Déclaration de la patiente</b>", body)]]
    for s in report["sections"]:
        text = "<br/>".join(f["text"] for f in s["findings"])
        title = f"<font color='{TRIAGE_COLORS['urgent']}'>● </font>{s['title']}" if s["alert"] else s["title"]
        rows.append([Paragraph(title, body), Paragraph(text, body)])
    table = Table(rows, colWidths=[4.3 * cm, 12.7 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FCE4EC")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E0B4C4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Paragraph("Conduite proposée", h2)]
    story += [Paragraph(f"• {r}", body) for r in report["recommendations"]]
    if doctor_comment:
        story += [Paragraph("Commentaire du médecin", h2), Paragraph(doctor_comment, body)]
    story += [Spacer(1, 14), Paragraph(report["disclaimer"], small)]
    doc.build(story)
    return buf.getvalue()
