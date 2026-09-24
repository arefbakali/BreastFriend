from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from auth import login_required
from database import dumps, execute, query
from questionnaire import CATEGORIES, generate_questions
import events
from services import (conversation, current_question_set, ensure_checkin_notifications, notify,
                      patient_summaries, patient_summary, report_row, send_message)

bp = Blueprint("doctor", __name__, url_prefix="/api/doctor")
DOCTOR = login_required(roles="doctor")
TRIAGE_ORDER = {"urgent": 0, "a_surveiller": 1, "rassurant": 2, None: 3}


def _own_patient(pid):
    return query("SELECT user_id FROM patient_profiles WHERE user_id = ? AND doctor_id = ?", (pid, g.user["id"]), one=True)


@bp.get("/dashboard")
@DOCTOR
def dashboard():
    ensure_checkin_notifications(g.user["id"])
    ids = [r["user_id"] for r in query("SELECT user_id FROM patient_profiles WHERE doctor_id = ?", (g.user["id"],))]
    pending = query("SELECT COUNT(*) AS n FROM reports WHERE doctor_id = ? AND reviewed = 0", (g.user["id"],), one=True)["n"]
    urgent = query("SELECT COUNT(*) AS n FROM reports WHERE doctor_id = ? AND reviewed = 0 AND triage = 'urgent'",
                   (g.user["id"],), one=True)["n"]
    today = datetime.now().strftime("%Y-%m-%d")
    todays = query("SELECT a.*, u.full_name AS patient_name FROM appointments a JOIN users u ON u.id = a.patient_id "
                   "WHERE a.doctor_id = ? AND substr(a.starts_at,1,10) = ? AND a.status != 'annule' ORDER BY a.starts_at",
                   (g.user["id"], today))
    return jsonify(stats={"patients": len(ids), "pending_reports": pending, "urgent_reports": urgent,
                          "appointments_today": len(todays)},
                   today=todays,
                   unread_notifications=query("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
                                              (g.user["id"],), one=True)["n"])


@bp.get("/patients")
@DOCTOR
def patients():
    q = (request.args.get("q") or "").strip().lower()
    items = patient_summaries(g.user["id"], q)
    items.sort(key=lambda p: (TRIAGE_ORDER.get(p["last_report"]["triage"] if p["last_report"] and not p["last_report"]["reviewed"] else None),
                              p["full_name"]))
    return jsonify(patients=items)


@bp.get("/patients/<int:pid>")
@DOCTOR
def patient_detail(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    summary = patient_summary(pid)
    reports = query("SELECT id, triage, risk_score, reviewed, doctor_comment, created_at FROM reports "
                    "WHERE patient_id = ? ORDER BY id DESC", (pid,))
    appts = query("SELECT * FROM appointments WHERE patient_id = ? ORDER BY starts_at DESC", (pid,))
    note = query("SELECT body, updated_at FROM doctor_notes WHERE doctor_id = ? AND patient_id = ?",
                 (g.user["id"], pid), one=True)
    history = query("SELECT substr(created_at,1,10) AS date, risk_score, triage FROM reports WHERE patient_id = ? "
                    "ORDER BY id", (pid,))
    return jsonify(patient=summary, reports=reports, appointments=appts, note=note, question_set=current_question_set(pid),
                   risk_history=history)


@bp.put("/patients/<int:pid>")
@DOCTOR
def update_patient(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    d = request.get_json(silent=True) or {}
    if d.get("status") and d["status"] not in ("prevention", "traitement", "remission"):
        return jsonify(error="Statut invalide."), 400
    for field in ("status", "treatment"):
        if field in d:
            execute(f"UPDATE patient_profiles SET {field} = ? WHERE user_id = ?", (d[field], pid))
    events.publish([g.user["id"], pid], "patient", {"patient_id": pid})
    return jsonify(patient=patient_summary(pid))


# ---- Questions de suivi -----------------------------------------------------
@bp.post("/patients/<int:pid>/questions/generate")
@DOCTOR
def regenerate_questions(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    status = query("SELECT status FROM patient_profiles WHERE user_id = ?", (pid,), one=True)["status"]
    questions, source = generate_questions(current_app.extensions["rag"], status or "prevention")
    execute("DELETE FROM question_sets WHERE patient_id = ? AND confirmed = 0", (pid,))
    execute("INSERT INTO question_sets (patient_id, doctor_id, questions_json, source) VALUES (?,?,?,?)",
            (pid, g.user["id"], dumps(questions), source))
    return jsonify(question_set=current_question_set(pid))


@bp.put("/patients/<int:pid>/questions")
@DOCTOR
def save_questions(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    d = request.get_json(silent=True) or {}
    questions = []
    for i, q in enumerate(d.get("questions") or []):
        text = (q.get("text") or "").strip()
        if not text:
            continue
        cat = q.get("category") if q.get("category") in CATEGORIES else "size_shape"
        item = {"id": f"q{i + 1}", "category": cat, "text": text}
        if q.get("rationale"):
            item["rationale"] = q["rationale"]
        questions.append(item)
    if len(questions) < 3:
        return jsonify(error="Le questionnaire doit contenir au moins 3 questions."), 400
    confirm = bool(d.get("confirm", True))
    execute("DELETE FROM question_sets WHERE patient_id = ? AND confirmed >= 0", (pid,))
    execute("INSERT INTO question_sets (patient_id, doctor_id, questions_json, source, confirmed, confirmed_at) "
            "VALUES (?,?,?,?,?,?)", (pid, g.user["id"], dumps(questions), d.get("source") or "doctor", int(confirm),
                                     datetime.now().strftime("%Y-%m-%d %H:%M") if confirm else None))
    if confirm:
        execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND kind = 'checkin' AND link LIKE ?",
                (g.user["id"], f"/doctor/patients/{pid}?%"))
        notify(pid, "questionnaire", "Votre questionnaire de suivi est prêt",
               f"{g.user['full_name']} a préparé vos questions pour ce mois.", link="/questionnaire")
    events.publish([g.user["id"], pid], "question_set", {"patient_id": pid})
    return jsonify(question_set=current_question_set(pid), categories={k: v["label"] for k, v in CATEGORIES.items()})


@bp.get("/categories")
@DOCTOR
def categories():
    return jsonify(categories={k: v["label"] for k, v in CATEGORIES.items()})


# ---- Comptes rendus -----------------------------------------------------------
@bp.get("/reports")
@DOCTOR
def reports():
    only_pending = request.args.get("pending") == "1"
    rows = query("SELECT r.id, r.patient_id, r.triage, r.risk_score, r.reviewed, r.created_at, u.full_name AS patient_name, "
                 "u.avatar FROM reports r JOIN users u ON u.id = r.patient_id WHERE r.doctor_id = ? "
                 + ("AND r.reviewed = 0 " if only_pending else "") + "ORDER BY r.reviewed, r.id DESC", (g.user["id"],))
    return jsonify(reports=rows)


@bp.get("/reports/<int:rid>")
@DOCTOR
def report_detail(rid):
    r = report_row(query("SELECT r.*, u.full_name AS patient_name, u.avatar FROM reports r JOIN users u "
                         "ON u.id = r.patient_id WHERE r.id = ? AND r.doctor_id = ?", (rid, g.user["id"]), one=True))
    if not r:
        return jsonify(error="Compte rendu introuvable."), 404
    qs = query("SELECT questions_json FROM question_sets WHERE id = ?", (r["question_set_id"],), one=True)
    from database import loads
    r["questions"] = loads(qs["questions_json"], []) if qs else []
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND kind = 'report' AND ref_id = ?", (g.user["id"], rid))
    return jsonify(report=r)


@bp.patch("/reports/<int:rid>")
@DOCTOR
def review_report(rid):
    r = query("SELECT * FROM reports WHERE id = ? AND doctor_id = ?", (rid, g.user["id"]), one=True)
    if not r:
        return jsonify(error="Compte rendu introuvable."), 404
    d = request.get_json(silent=True) or {}
    comment = (d.get("doctor_comment") or "").strip()
    execute("UPDATE reports SET reviewed = ?, doctor_comment = ? WHERE id = ?",
            (int(d.get("reviewed", True)), comment or r["doctor_comment"], rid))
    notify(r["patient_id"], "report", "Votre médecin a lu votre compte rendu",
           comment[:160] if comment else "Consultez-le dans « Mes comptes rendus ».", link=f"/reports/{rid}", ref_id=rid)
    events.publish([g.user["id"], r["patient_id"]], "report", {"id": rid, "patient_id": r["patient_id"]})
    return jsonify(ok=True)


# ---- Rendez-vous / calendrier -------------------------------------------------
@bp.get("/appointments")
@DOCTOR
def appointments():
    start = request.args.get("from", "0000")
    end = request.args.get("to", "9999")
    rows = query("SELECT a.*, u.full_name AS patient_name, u.avatar FROM appointments a JOIN users u ON u.id = a.patient_id "
                 "WHERE a.doctor_id = ? AND a.starts_at >= ? AND a.starts_at <= ? ORDER BY a.starts_at",
                 (g.user["id"], start, end + "T23:59"))
    return jsonify(appointments=rows)


def _valid_dt(value):
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


@bp.post("/appointments")
@DOCTOR
def create_appointment():
    d = request.get_json(silent=True) or {}
    pid = d.get("patient_id")
    starts = _valid_dt(d.get("starts_at"))
    if not pid:
        return jsonify(error="Patiente invalide."), 400
    if not _own_patient(pid):              # patiente d'un autre médecin : même réponse qu'inexistante
        return jsonify(error="Patiente introuvable."), 404
    if not starts:
        return jsonify(error="Date et heure invalides."), 400
    kind = d.get("kind") if d.get("kind") in ("consultation", "check-in", "mammographie", "chimiotherapie") else "consultation"
    aid = execute("INSERT INTO appointments (patient_id, doctor_id, starts_at, kind, notes) VALUES (?,?,?,?,?)",
                  (pid, g.user["id"], starts, kind, d.get("notes")))
    notify(pid, "appointment", "Nouveau rendez-vous", f"{kind.capitalize()} le {starts.replace('T', ' à ')}",
           link="/doctor-contact", ref_id=aid)
    ensure_checkin_notifications(g.user["id"])
    events.publish([g.user["id"], pid], "appointment", {"id": aid, "patient_id": pid})
    return jsonify(appointment=query("SELECT * FROM appointments WHERE id = ?", (aid,), one=True)), 201


@bp.patch("/appointments/<int:aid>")
@DOCTOR
def update_appointment(aid):
    a = query("SELECT * FROM appointments WHERE id = ? AND doctor_id = ?", (aid, g.user["id"]), one=True)
    if not a:
        return jsonify(error="Rendez-vous introuvable."), 404
    d = request.get_json(silent=True) or {}
    starts = _valid_dt(d["starts_at"]) if d.get("starts_at") else a["starts_at"]
    if not starts:
        return jsonify(error="Date et heure invalides."), 400
    status = d.get("status") if d.get("status") in ("prevu", "fait", "annule") else a["status"]
    execute("UPDATE appointments SET starts_at = ?, status = ?, notes = ?, kind = ? WHERE id = ?",
            (starts, status, d.get("notes", a["notes"]), d.get("kind", a["kind"]), aid))
    if status == "annule" and a["status"] != "annule":
        notify(a["patient_id"], "appointment", "Rendez-vous annulé", f"Le rendez-vous du {a['starts_at'].replace('T', ' à ')} est annulé.",
               link="/doctor-contact", ref_id=aid)
    events.publish([g.user["id"], a["patient_id"]], "appointment", {"id": aid, "patient_id": a["patient_id"]})
    return jsonify(appointment=query("SELECT * FROM appointments WHERE id = ?", (aid,), one=True))


@bp.delete("/appointments/<int:aid>")
@DOCTOR
def delete_appointment(aid):
    a = query("SELECT patient_id FROM appointments WHERE id = ? AND doctor_id = ?", (aid, g.user["id"]), one=True)
    if not a:
        return jsonify(error="Rendez-vous introuvable."), 404
    execute("DELETE FROM appointments WHERE id = ? AND doctor_id = ?", (aid, g.user["id"]))
    events.publish([g.user["id"], a["patient_id"]], "appointment", {"id": aid, "patient_id": a["patient_id"]})
    return jsonify(ok=True)


# ---- Notes --------------------------------------------------------------------
@bp.get("/notes")
@DOCTOR
def get_note():
    pid = request.args.get("patient_id", type=int)
    note = query("SELECT body, updated_at FROM doctor_notes WHERE doctor_id = ? AND patient_id IS ?",
                 (g.user["id"], pid), one=True)
    return jsonify(note=note or {"body": "", "updated_at": None})


@bp.put("/notes")
@DOCTOR
def save_note():
    d = request.get_json(silent=True) or {}
    pid = d.get("patient_id")
    if pid is not None and not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    body = (d.get("body") or "")[:20000]
    existing = query("SELECT id FROM doctor_notes WHERE doctor_id = ? AND patient_id IS ?", (g.user["id"], pid), one=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if existing:
        execute("UPDATE doctor_notes SET body = ?, updated_at = ? WHERE id = ?", (body, now, existing["id"]))
    else:
        execute("INSERT INTO doctor_notes (doctor_id, patient_id, body, updated_at) VALUES (?,?,?,?)",
                (g.user["id"], pid, body, now))
    return jsonify(note={"body": body, "updated_at": now})


# ---- Messages -------------------------------------------------------------------
@bp.get("/patients/<int:pid>/messages")
@DOCTOR
def messages(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    execute("UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ?", (pid, g.user["id"]))
    return jsonify(messages=conversation(g.user["id"], pid))


@bp.post("/patients/<int:pid>/messages")
@DOCTOR
def post_message(pid):
    if not _own_patient(pid):
        return jsonify(error="Patiente introuvable."), 404
    body = ((request.get_json(silent=True) or {}).get("body") or "").strip()
    if not body:
        return jsonify(error="Message vide."), 400
    send_message(g.user, pid, body[:3000])
    return jsonify(messages=conversation(g.user["id"], pid)), 201
