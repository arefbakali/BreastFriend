"""Questionnaire post-autopalpation : génération des questions (RAG) et triage.

* generate_questions : chaque question est ancrée dans un passage du corpus
  (justification affichée au médecin). Avec un LLM, les questions sont
  reformulées / complétées à partir du contexte récupéré ; sans LLM, elles sont
  sélectionnées dans une banque validée selon le profil de la patiente.
* parse_answer : interprète une réponse libre (« Oui j'ai remarqué... », « non »).
* triage : score de vigilance déterministe et explicable (jamais un diagnostic).
"""
import json
import logging
import re
import unicodedata

import llm

log = logging.getLogger("breastfriend.questionnaire")

# poids = importance clinique d'une réponse « oui » ; invert = « non » est le signal
CATEGORIES = {
    "size_shape": {"label": "Taille / forme", "weight": 2},
    "lump": {"label": "Boule / masse", "weight": 3},
    "pain": {"label": "Douleur", "weight": 1},
    "skin": {"label": "Peau", "weight": 3},
    "nipple_discharge": {"label": "Écoulement du mamelon", "weight": 3},
    "nipple_change": {"label": "Aspect du mamelon", "weight": 2},
    "lymph": {"label": "Ganglions", "weight": 3},
    "family_history": {"label": "Antécédents familiaux", "weight": 1},
    "self_exam": {"label": "Autopalpation régulière", "weight": 0, "invert": True},
    "tenderness": {"label": "Sensibilité", "weight": 1},
    "fever": {"label": "Fièvre", "weight": 5},
    "fatigue": {"label": "Fatigue", "weight": 1},
    "arm_swelling": {"label": "Gonflement du bras", "weight": 2},
    "bone_pain": {"label": "Douleurs osseuses", "weight": 2},
    "scar": {"label": "Cicatrice", "weight": 2},
    "mood": {"label": "Moral", "weight": 1},
}

QUESTION_BANK = [
    {"category": "size_shape", "text": "Avez-vous remarqué des changements dans la taille ou la forme de vos seins ?",
     "query": "modification taille forme sein", "profiles": ["all"]},
    {"category": "lump", "text": "Avez-vous senti une boule, un épaississement ou une anomalie en palpant vos seins ?",
     "query": "boule épaississement nouveau sein palpation", "profiles": ["all"]},
    {"category": "pain", "text": "Ressentez-vous une douleur particulière dans la zone concernée ?",
     "query": "douleur mammaire localisée persistante", "profiles": ["all"]},
    {"category": "skin", "text": "Avez-vous observé une rougeur, un creux, une ride ou un aspect de peau d'orange sur la peau du sein ?",
     "query": "peau rétracte rougeur peau d'orange", "profiles": ["all"]},
    {"category": "nipple_discharge", "text": "Avez-vous observé un écoulement du mamelon, en particulier clair ou sanglant ?",
     "query": "écoulement spontané mamelon sanglant", "profiles": ["all"]},
    {"category": "nipple_change", "text": "Votre mamelon s'est-il rétracté vers l'intérieur ou a-t-il changé d'aspect (croûtes, eczéma) ?",
     "query": "mamelon rétracte change aspect croûtes", "profiles": ["all"]},
    {"category": "lymph", "text": "Avez-vous senti un ganglion gonflé ou dur sous l'aisselle ou au-dessus de la clavicule ?",
     "query": "ganglion aisselle clavicule", "profiles": ["all"]},
    {"category": "family_history", "text": "Avez-vous des antécédents de cancer du sein ou de l'ovaire dans votre famille proche ?",
     "query": "antécédents familiaux mère sœur BRCA", "profiles": ["prevention"]},
    {"category": "self_exam", "text": "Réalisez-vous votre autopalpation chaque mois ?",
     "query": "autopalpation une fois par mois", "profiles": ["prevention", "remission"]},
    {"category": "tenderness", "text": "Vos seins sont-ils plus sensibles ou tendus que d'habitude en dehors de vos règles ?",
     "query": "seins sensibles gonflés avant les règles cycle", "profiles": ["prevention"]},
    {"category": "fever", "text": "Avez-vous eu de la fièvre (38 °C ou plus) ou des frissons depuis votre dernière cure ?",
     "query": "fièvre chimiothérapie neutropénie urgence", "profiles": ["traitement"]},
    {"category": "fatigue", "text": "Ressentez-vous une fatigue inhabituelle qui vous empêche de faire vos activités quotidiennes ?",
     "query": "fatigue activité physique douce", "profiles": ["traitement", "remission"]},
    {"category": "arm_swelling", "text": "Avez-vous remarqué un gonflement, une lourdeur ou une tension dans le bras du côté opéré ?",
     "query": "lymphœdème bras gonflement lourdeur", "profiles": ["traitement", "remission"]},
    {"category": "bone_pain", "text": "Avez-vous des douleurs osseuses persistantes et inhabituelles ?",
     "query": "douleur osseuse persistante signaler", "profiles": ["remission"]},
    {"category": "scar", "text": "Avez-vous remarqué une modification de votre cicatrice (rougeur, grosseur, écoulement) ?",
     "query": "modification cicatrice sein opéré", "profiles": ["traitement", "remission"]},
    {"category": "mood", "text": "Vous êtes-vous sentie triste, découragée ou anxieuse la plupart du temps ces deux dernières semaines ?",
     "query": "tristesse deux semaines psychologue soutien", "profiles": ["all"]},
]

LLM_PROMPT = """Tu aides un oncologue à préparer le questionnaire mensuel post-autopalpation d'une patiente \
(profil : {profile}). À partir du CONTEXTE médical ci-dessous, rédige {n} questions fermées (réponse oui/non), \
claires, bienveillantes, en français, adaptées à une patiente non-médecin.
Chaque question doit porter sur UNE catégorie parmi : {categories}.
Réponds UNIQUEMENT avec un JSON de la forme :
{{"questions": [{{"category": "lump", "text": "..."}}]}}

CONTEXTE :
{context}
"""


def _norm(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def _search(rag, query, k):
    """Recherche RAG tolérante : sans moteur prêt, les questions restent utilisables sans justification."""
    if rag is None:
        return []
    try:
        passages, _ = rag.search(query, candidates=6, final_k=k, use_reranker=False, timeout=5)
        return passages
    except Exception as exc:  # moteur en démarrage / indisponible
        log.info("Justification RAG indisponible : %s", exc)
        return []


def _with_rationale(rag, q):
    hits = _search(rag, q.get("query") or q["text"], 1)
    if hits:
        h = hits[0]
        q["rationale"] = {"title": h.title, "section": h.section, "source": h.filename,
                          "page": h.page_start, "excerpt": h.text[:260] + ("…" if len(h.text) > 260 else "")}
    return q


def _bank_questions(profile):
    return [dict(q) for q in QUESTION_BANK if "all" in q["profiles"] or profile in q["profiles"]]


def generate_questions(rag, profile="prevention", n=None):
    """Renvoie (questions, source). Chaque question : id, category, text, rationale."""
    bank = _bank_questions(profile)
    n = n or len(bank)
    questions, source = None, "rag"

    if llm.is_enabled():
        queries = " ".join(q["query"] for q in bank)
        hits = _search(rag, f"signes d'alerte autopalpation suivi {profile} {queries}", 6)
        context = "\n\n".join(f"- {h.section} : {h.text}" for h in hits)
        try:
            raw = llm.chat([{"role": "user", "content": LLM_PROMPT.format(
                profile=profile, n=n, categories=", ".join(q["category"] for q in bank), context=context)}],
                temperature=0.3, json_mode=True)
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            parsed = [q for q in data.get("questions", [])
                      if isinstance(q, dict) and q.get("category") in CATEGORIES and len(q.get("text", "")) > 10]
            if len(parsed) >= 4:
                questions = [{"category": q["category"], "text": q["text"].strip()} for q in parsed[:n]]
                source = "rag+llm"
        except (llm.LLMUnavailable, ValueError, KeyError, TypeError):
            questions = None

    if questions is None:
        questions = bank[:n]

    out = []
    for i, q in enumerate(questions):
        q = _with_rationale(rag, dict(q))
        q.pop("query", None)
        q.pop("profiles", None)
        q["id"] = f"q{i + 1}"
        out.append(q)
    return out, source


YES = {"oui", "yes", "ouais", "si", "yep", "exact", "effectivement", "bien sur", "eh", "ay", "iyh", "ih", "naam"}
NO = {"non", "no", "nan", "pas", "aucun", "aucune", "jamais", "rien", "le", "la"}


def parse_answer(text):
    """Interprète une réponse libre -> 'yes' | 'no' | 'unknown'."""
    t = _norm(text)
    if not t:
        return "unknown"
    if re.search(r"\b(je ne sais pas|sais pas|je sais pas|peut-etre|pas sur|pas certaine)\b", t):
        return "unknown"
    first = re.findall(r"[a-z]+", t)[:1]
    if first and first[0] in ("oui", "yes", "ouais", "si", "effectivement", "naam", "iyh", "ih"):
        return "yes"
    if first and first[0] in ("non", "no", "nan", "jamais", "aucun", "aucune", "rien"):
        return "no"
    if re.search(r"\b(ne|n)\b.*\b(pas|jamais|aucun|aucune|rien)\b", t) or re.search(r"\bpas (de|d)\b", t):
        return "no"
    if re.search(r"\b(j ai|j'ai|jai|je ressens|je sens|j'observe|il y a|remarque)\b", t):
        return "yes"
    return "unknown"


def triage(questions, answers):
    """answers : {question_id: {"value": yes|no|unknown, "detail": str}}"""
    score, flags, notes = 0, [], []
    urgent = False
    for q in questions:
        a = answers.get(q["id"], {})
        value = a.get("value", "unknown")
        meta = CATEGORIES.get(q["category"], {"label": q["category"], "weight": 1})
        if meta.get("invert"):
            if value == "no":
                notes.append("Autopalpation non régulière : rappel d'éducation à prévoir.")
            continue
        if value == "yes":
            score += meta["weight"]
            flags.append({"category": q["category"], "label": meta["label"], "weight": meta["weight"],
                          "detail": a.get("detail", "")})
            if q["category"] == "fever":
                urgent = True
        elif value == "unknown" and meta["weight"] >= 3:
            notes.append(f"Réponse incertaine pour « {meta['label']} » : à préciser en consultation.")

    red = sum(1 for f in flags if f["weight"] >= 3)
    if urgent or score >= 7 or red >= 2:
        level = "urgent"
    elif score >= 2 or red >= 1:
        level = "a_surveiller"
    else:
        level = "rassurant"
    return {"level": level, "score": score, "flags": flags, "notes": notes}


TRIAGE_LABELS = {
    "rassurant": "Rassurant",
    "a_surveiller": "À surveiller",
    "urgent": "Prioritaire",
}
