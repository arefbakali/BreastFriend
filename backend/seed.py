"""Données de démonstration (dates calculées par rapport à aujourd'hui).

Tous les comptes : mot de passe « demo1234 ».
"""
from datetime import date, datetime, timedelta

from flask import current_app

from auth import hash_password
from database import dumps, execute, query
from questionnaire import generate_questions, triage
from report import build_report
from services import notify

PASSWORD = "demo1234"


def _dt(days, hour=10, minute=0):
    d = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days)
    return d.strftime("%Y-%m-%dT%H:%M")


def _user(username, role, name, **kw):
    return execute(
        "INSERT INTO users (username, password_hash, role, full_name, email, phone, specialty, avatar) VALUES (?,?,?,?,?,?,?,?)",
        (username, hash_password(PASSWORD), role, name, kw.get("email"), kw.get("phone"), kw.get("specialty"), kw.get("avatar")))


def _patient(username, name, doctor_id, avatar, status, treatment, birth, family=0, last_exam=None):
    uid = _user(username, "patient", name, email=f"{username}@exemple.tn", phone="+216 20 000 000", avatar=avatar)
    execute("INSERT INTO patient_profiles (user_id, doctor_id, birth_date, status, treatment, family_history, last_self_exam) "
            "VALUES (?,?,?,?,?,?,?)", (uid, doctor_id, birth, status, treatment, family, last_exam))
    return uid


def _report(uid, doctor_id, status, texts, days_ago, reviewed=False, comment=None):
    """Crée un compte rendu en passant par le vrai pipeline (questions RAG -> triage -> rapport)."""
    questions, source = generate_questions(current_app.extensions["rag"], status)
    qid = execute("INSERT INTO question_sets (patient_id, doctor_id, questions_json, source, confirmed) VALUES (?,?,?,?,-1)",
                  (uid, doctor_id, dumps(questions), source))
    answers = {}
    for q in questions:
        value, detail = texts.get(q["category"], ("no", ""))
        answers[q["id"]] = {"value": value, "detail": detail}
    tri = triage(questions, answers)
    patient = query("SELECT * FROM users WHERE id = ?", (uid,), one=True)
    rep = build_report(patient, questions, answers, tri)
    created = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    rep["generated_at"] = created[:16]
    rid = execute("INSERT INTO reports (patient_id, doctor_id, question_set_id, answers_json, report_json, triage, risk_score, "
                  "reviewed, doctor_comment, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (uid, doctor_id, qid, dumps(answers), dumps(rep), tri["level"], tri["score"], int(reviewed), comment, created))
    if not reviewed:
        notify(doctor_id, "report", f"Le compte rendu de {patient['full_name']} est prêt",
               f"Niveau de vigilance : {rep['triage']['label']}.", link=f"/doctor/reports/{rid}", ref_id=rid)
    return rid


def seed_if_empty():
    if query("SELECT id FROM users LIMIT 1", one=True):
        return
    print("[seed] Création des données de démonstration...")
    amel = _user("dr.amel", "doctor", "Dr Amel Ben Salah", specialty="Oncologue", email="amel.bensalah@exemple.tn",
                 phone="+216 71 000 000")
    karim = _user("dr.karim", "doctor", "Dr Karim Trabelsi", specialty="Gynécologue", email="karim.trabelsi@exemple.tn",
                  phone="+216 71 111 111")

    today = date.today()
    salma = _patient("salma", "Salma Gharbi", amel, "/static/avatars/patient3.jpg", "prevention", None, "1994-04-12",
                     family=1, last_exam=(today - timedelta(days=35)).isoformat())
    leila = _patient("leila", "Leïla Mansouri", amel, "/static/avatars/patient1.jpg", "remission",
                     "Hormonothérapie (tamoxifène) depuis 2 ans", "1961-09-03", last_exam=(today - timedelta(days=3)).isoformat())
    meriem = _patient("meriem", "Meriem Haddad", amel, "/static/avatars/patient2.jpg", "traitement",
                      "Chimiothérapie adjuvante, cycle 3/6", "1983-01-27", last_exam=(today - timedelta(days=1)).isoformat())
    ines = _patient("ines", "Inès Jaziri", amel, "/static/avatars/patient4.jpg", "prevention", None, "1990-06-18")
    _patient("yasmine", "Yasmine Chaabane", karim, None, "prevention", None, "1998-11-02")

    appts = [
        (salma, _dt(2, 9, 30), "check-in", "Check-in mensuel", "prevu"),
        (leila, _dt(9, 11), "consultation", "Contrôle semestriel + résultats mammographie", "prevu"),
        (meriem, _dt(5, 14), "chimiotherapie", "Cycle 4", "prevu"),
        (meriem, _dt(12, 10), "consultation", "Tolérance chimiothérapie", "prevu"),
        (ines, _dt(24, 15), "consultation", "Première consultation de prévention", "prevu"),
        (leila, _dt(-30, 10), "mammographie", "Mammographie annuelle", "fait"),
        (salma, _dt(-28, 9, 30), "check-in", None, "fait"),
        (meriem, _dt(0, 16), "consultation", "Point bilan sanguin", "prevu"),
    ]
    for pid, when, kind, notes, status in appts:
        execute("INSERT INTO appointments (patient_id, doctor_id, starts_at, kind, notes, status) VALUES (?,?,?,?,?,?)",
                (pid, amel, when, kind, notes, status))

    _report(salma, amel, "prevention", {"family_history": ("yes", "Ma tante maternelle"), "self_exam": ("yes", "")},
            days_ago=30, reviewed=True, comment="Rien d'anormal. Continuez l'autopalpation chaque mois, Salma.")
    _report(leila, amel, "remission", {
        "size_shape": ("yes", "Oui j'ai remarqué un changement dans la taille de mes seins."),
        "pain": ("yes", "Oui je ressens une douleur du côté gauche."),
        "self_exam": ("yes", ""), "fatigue": ("yes", "Plus fatiguée le soir"),
    }, days_ago=3)
    _report(meriem, amel, "traitement", {
        "fever": ("yes", "38,4 °C hier soir avec des frissons"), "fatigue": ("yes", "Très fatiguée depuis la cure"),
        "mood": ("yes", "Je pleure souvent"),
    }, days_ago=1)

    execute("INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?,?,?,?)",
            (leila, amel, "Bonjour Docteur, j'ai rempli le questionnaire. Je ressens une petite douleur depuis une semaine, "
                          "est-ce que je dois m'inquiéter ?", (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")))
    execute("INSERT INTO messages (sender_id, recipient_id, body, is_read, created_at) VALUES (?,?,?,?,?)",
            (amel, leila, "Bonjour Madame Mansouri, merci pour votre message. Je regarde votre compte rendu et je vous "
                          "propose de venir en consultation.", 1, (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")))
    execute("INSERT INTO doctor_notes (doctor_id, patient_id, body) VALUES (?,?,?)",
            (amel, None, "• Rappeler le laboratoire pour le bilan de Meriem\n• Staff RCP jeudi 14h"))
    execute("INSERT INTO doctor_notes (doctor_id, patient_id, body) VALUES (?,?,?)",
            (amel, leila, "Tumorectomie gauche il y a 3 ans. Tamoxifène bien toléré. Surveiller douleurs articulaires."))
    print("[seed] OK — comptes : dr.amel, dr.karim, salma, leila, meriem, ines, yasmine (mot de passe : demo1234)")
