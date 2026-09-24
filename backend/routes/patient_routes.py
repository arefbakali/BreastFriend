from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

import events
from auth import login_required, public_user
from database import dumps, execute, loads, query
from questionnaire import generate_questions, parse_answer, triage
from report import build_report
from services import (affirmation_of_the_day, conversation, current_question_set, next_appointment,
                      next_self_exam, notify, report_row, send_message)

bp = Blueprint("patient", __name__, url_prefix="/api/patient")
PATIENT = login_required(roles="patient")


def _profile():
    return query("SELECT * FROM patient_profiles WHERE user_id = ?", (g.user["id"],), one=True) or {}


@bp.get("/dashboard")
@PATIENT
def dashboard():
    prof = _profile()
    doctor = query("SELECT id, full_name, specialty, email, phone, avatar FROM users WHERE id = ?",
                   (prof.get("doctor_id") or 0,), one=True)
    last = report_row(query("SELECT * FROM reports WHERE patient_id = ? ORDER BY id DESC LIMIT 1",
                            (g.user["id"],), one=True))
    wig = query("SELECT id, created_at FROM wig_analyses WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (g.user["id"],), one=True)
    return jsonify(
        user=public_user(g.user),
        profile={k: prof.get(k) for k in ("status", "treatment", "birth_date", "family_history", "last_self_exam", "reminder_day")},
        doctor=doctor,
        next_appointment=next_appointment(g.user["id"]),
        self_exam=next_self_exam(prof),
        affirmation=affirmation_of_the_day(g.user["id"]),
        last_report={"id": last["id"], "triage": last["triage"], "created_at": last["created_at"],
                     "reviewed": last["reviewed"], "doctor_comment": last["doctor_comment"]} if last else None,
        last_wig_analysis=wig,
        unread_notifications=query("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
                                   (g.user["id"],), one=True)["n"],
    )


@bp.put("/profile")
@PATIENT
def update_profile():
    d = request.get_json(silent=True) or {}
    if "reminder_day" in d:
        day = int(d["reminder_day"])
        if not 1 <= day <= 28:
            return jsonify(error="Le jour de rappel doit être compris entre 1 et 28."), 400
        execute("UPDATE patient_profiles SET reminder_day = ? WHERE user_id = ?", (day, g.user["id"]))
    for field in ("email", "phone"):
        if field in d:
            execute(f"UPDATE users SET {field} = ? WHERE id = ?", (d[field], g.user["id"]))
    return jsonify(ok=True)


@bp.post("/self-exam")
@PATIENT
def self_exam_done():
    today = date.today().isoformat()
    execute("INSERT INTO self_exams (patient_id) VALUES (?)", (g.user["id"],))
    execute("UPDATE patient_profiles SET last_self_exam = ? WHERE user_id = ?", (today, g.user["id"]))
    events.publish([g.user["id"], _profile().get("doctor_id")], "patient", {"patient_id": g.user["id"]})
    return jsonify(ok=True, self_exam=next_self_exam(_profile()))


@bp.get("/questionnaire")
@PATIENT
def get_questionnaire():
    qs = current_question_set(g.user["id"])
    if not qs:
        prof = _profile()
        questions, source = generate_questions(current_app.extensions["rag"], prof.get("status") or "prevention")
        qid = execute("INSERT INTO question_sets (patient_id, doctor_id, questions_json, source) VALUES (?,?,?,?)",
                      (g.user["id"], prof.get("doctor_id"), dumps(questions), source))
        qs = current_question_set(g.user["id"])
        qs["id"] = qid
    # la patiente ne voit pas les justifications internes
    public_q = [{"id": q["id"], "text": q["text"], "category": q["category"]} for q in qs["questions"]]
    return jsonify(question_set_id=qs["id"], confirmed=bool(qs["confirmed"]), questions=public_q)


@bp.post("/questionnaire")
@PATIENT
def submit_questionnaire():
    d = request.get_json(silent=True) or {}
    qs = query("SELECT * FROM question_sets WHERE id = ? AND patient_id = ?", (d.get("question_set_id"), g.user["id"]), one=True)
    if not qs:
        return jsonify(error="Questionnaire introuvable."), 404
    questions = loads(qs["questions_json"], [])
    raw = d.get("answers") or {}
    answers = {}
    for q in questions:
        a = raw.get(q["id"])
        if a is None:
            return jsonify(error=f"Merci de répondre à toutes les questions ({q['text']})."), 400
        if isinstance(a, str):
            a = {"text": a}
        value = a.get("value")
        text = (a.get("text") or a.get("detail") or "").strip()
        if value not in ("yes", "no", "unknown"):
            value = parse_answer(text)
        detail = text if text and text.lower() not in ("oui", "non") else ""
        answers[q["id"]] = {"value": value, "detail": detail[:500]}

    tri = triage(questions, answers)
    prof = _profile()
    rep = build_report(g.user, questions, answers, tri)
    rid = execute(
        "INSERT INTO reports (patient_id, doctor_id, question_set_id, answers_json, report_json, triage, risk_score) "
        "VALUES (?,?,?,?,?,?,?)",
        (g.user["id"], prof.get("doctor_id"), qs["id"], dumps(answers), dumps(rep), tri["level"], tri["score"]))
    # le questionnaire de ce mois est consommé : le prochain sera régénéré / confirmé
    execute("UPDATE question_sets SET confirmed = -1 WHERE id = ?", (qs["id"],))
    execute("UPDATE patient_profiles SET last_self_exam = ? WHERE user_id = ?", (date.today().isoformat(), g.user["id"]))
    if prof.get("doctor_id"):
        prefix = "⚠ " if tri["level"] == "urgent" else ""
        notify(prof["doctor_id"], "report", f"{prefix}Le compte rendu de {g.user['full_name']} est prêt",
               f"Niveau de vigilance : {rep['triage']['label']}.", link=f"/doctor/reports/{rid}", ref_id=rid)
    events.publish([g.user["id"], prof.get("doctor_id")], "report", {"id": rid, "patient_id": g.user["id"]})
    return jsonify(report_id=rid, triage=rep["triage"], summary=rep["summary"],
                   message=_patient_message(tri["level"])), 201


def _patient_message(level):
    if level == "urgent":
        return ("Merci. Certaines de vos réponses doivent être vues rapidement : votre médecin a été prévenu. "
                "Si vous avez de la fièvre pendant une chimiothérapie ou si vous vous sentez mal, "
                "appelez les urgences (SAMU 190) sans attendre.")
    if level == "a_surveiller":
        return ("Merci. Vous avez signalé un ou plusieurs changements : votre médecin a reçu votre compte rendu "
                "et pourra vous proposer un rendez-vous. La plupart des changements sont bénins, mais il est "
                "important de les faire vérifier.")
    return "Merci, rien d'inquiétant n'a été signalé. Votre compte rendu a été transmis à votre médecin. Au mois prochain !"


@bp.get("/reports")
@PATIENT
def reports():
    rows = query("SELECT id, triage, risk_score, reviewed, doctor_comment, created_at FROM reports "
                 "WHERE patient_id = ? ORDER BY id DESC", (g.user["id"],))
    return jsonify(reports=rows)


@bp.get("/reports/<int:rid>")
@PATIENT
def report_detail(rid):
    r = report_row(query("SELECT * FROM reports WHERE id = ? AND patient_id = ?", (rid, g.user["id"]), one=True))
    if not r:
        return jsonify(error="Compte rendu introuvable."), 404
    return jsonify(report=r)


@bp.get("/appointments")
@PATIENT
def appointments():
    rows = query("SELECT a.*, u.full_name AS doctor_name FROM appointments a JOIN users u ON u.id = a.doctor_id "
                 "WHERE a.patient_id = ? ORDER BY a.starts_at DESC", (g.user["id"],))
    return jsonify(appointments=rows)


@bp.get("/messages")
@PATIENT
def messages():
    doctor_id = _profile().get("doctor_id")
    if not doctor_id:
        return jsonify(messages=[], doctor=None)
    execute("UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ?", (doctor_id, g.user["id"]))
    doctor = query("SELECT id, full_name, specialty, email, phone, avatar FROM users WHERE id = ?", (doctor_id,), one=True)
    return jsonify(messages=conversation(g.user["id"], doctor_id), doctor=doctor)


@bp.post("/messages")
@PATIENT
def post_message():
    body = ((request.get_json(silent=True) or {}).get("body") or "").strip()
    doctor_id = _profile().get("doctor_id")
    if not body:
        return jsonify(error="Message vide."), 400
    if not doctor_id:
        return jsonify(error="Aucun médecin associé à votre compte."), 400
    send_message(g.user, doctor_id, body[:3000])
    return jsonify(messages=conversation(g.user["id"], doctor_id)), 201
