"""Logique métier partagée entre les routes (notifications, rendez-vous...)."""
from datetime import date, datetime, timedelta

import events
from database import dumps, execute, loads, query

AFFIRMATIONS = [
    "Tu es bien plus forte que tu ne le crois, et tu n'es pas seule.",
    "Ta beauté ne tient pas à tes cheveux : elle est dans ton regard, ton rire et ton courage.",
    "Aujourd'hui, un petit pas suffit. Sois fière de chacun d'eux.",
    "Prendre soin de toi n'est pas un luxe, c'est une force.",
    "Tu as le droit d'avoir des jours difficiles. Demain est une nouvelle page.",
    "Chaque cicatrice raconte une victoire. Tu es une guerrière.",
    "Tu mérites la même douceur que celle que tu offres aux autres.",
    "Respire. Tu fais de ton mieux, et c'est déjà beaucoup.",
    "Ton corps se bat pour toi : remercie-le avec tendresse.",
    "La lumière que tu portes ne s'éteint pas pendant les tempêtes.",
    "Tu es belle, aujourd'hui et tous les jours.",
    "Autour de toi, une communauté de femmes marche à tes côtés.",
]


def affirmation_of_the_day(user_id):
    idx = (date.today().toordinal() + int(user_id)) % len(AFFIRMATIONS)
    return AFFIRMATIONS[idx]


def notify(user_id, kind, title, body="", link=None, ref_id=None):
    nid = execute(
        "INSERT INTO notifications (user_id, kind, title, body, link, ref_id) VALUES (?,?,?,?,?,?)",
        (user_id, kind, title, body, link, ref_id),
    )
    events.publish([user_id], "notification", {"id": nid, "kind": kind, "title": title})
    return nid


def next_appointment(patient_id):
    return query(
        "SELECT a.*, u.full_name AS doctor_name FROM appointments a JOIN users u ON u.id = a.doctor_id "
        "WHERE a.patient_id = ? AND a.status = 'prevu' AND a.starts_at >= ? ORDER BY a.starts_at LIMIT 1",
        (patient_id, datetime.now().strftime("%Y-%m-%dT%H:%M")), one=True)


def next_self_exam(profile):
    """Prochaine autopalpation : le jour de rappel choisi, chaque mois."""
    import calendar

    day = int(profile.get("reminder_day") or 1)
    today = date.today()
    last = profile.get("last_self_exam")
    done_this_month = bool(last) and last[:7] == today.strftime("%Y-%m")

    def month_date(y, m):
        return date(y, m, min(day, calendar.monthrange(y, m)[1]))

    if done_this_month:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        target, due = month_date(y, m), False
    else:
        target = month_date(today.year, today.month)
        due = target <= today
    return {"date": target.isoformat(), "due": due, "done_this_month": done_this_month,
            "days_left": (target - today).days}


def current_question_set(patient_id):
    qs = query("SELECT * FROM question_sets WHERE patient_id = ? AND confirmed >= 0 ORDER BY confirmed DESC, id DESC LIMIT 1",
               (patient_id,), one=True)
    if qs:
        qs["questions"] = loads(qs.pop("questions_json"), [])
    return qs


def ensure_checkin_notifications(doctor_id):
    """Crée « La patiente a son check-in dans 2 jours ; confirmez-vous ses questions ? »."""
    now = datetime.now()
    horizon = (now + timedelta(days=2)).replace(hour=23, minute=59)
    rows = query(
        "SELECT a.*, u.full_name FROM appointments a JOIN users u ON u.id = a.patient_id "
        "WHERE a.doctor_id = ? AND a.status = 'prevu' AND a.kind IN ('check-in', 'consultation') "
        "AND a.starts_at BETWEEN ? AND ?",
        (doctor_id, now.strftime("%Y-%m-%dT%H:%M"), horizon.strftime("%Y-%m-%dT%H:%M")))
    for a in rows:
        exists = query("SELECT id FROM notifications WHERE user_id = ? AND kind = 'checkin' AND ref_id = ?",
                       (doctor_id, a["id"]), one=True)
        if exists:
            continue
        qs = query("SELECT id FROM question_sets WHERE patient_id = ? AND confirmed = 1 AND confirmed_at >= ?",
                   (a["patient_id"], (now - timedelta(days=20)).strftime("%Y-%m-%d")), one=True)
        if qs:
            continue
        when = datetime.fromisoformat(a["starts_at"])
        days = (when.date() - now.date()).days
        delay = "aujourd'hui" if days <= 0 else "demain" if days == 1 else f"dans {days} jours"
        label = "check-in" if a["kind"] == "check-in" else "rendez-vous"
        notify(doctor_id, "checkin", f"{a['full_name']} a son {label} {delay}",
               "Confirmez-vous ses questions de suivi ?", link=f"/doctor/patients/{a['patient_id']}?tab=questions",
               ref_id=a["id"])


def patient_summary(user_id):
    u = query("SELECT u.*, p.* FROM users u JOIN patient_profiles p ON p.user_id = u.id WHERE u.id = ?",
              (user_id,), one=True)
    if not u:
        return None
    last = query("SELECT id, triage, risk_score, created_at, reviewed FROM reports WHERE patient_id = ? "
                 "ORDER BY id DESC LIMIT 1", (user_id,), one=True)
    appt = next_appointment(user_id)
    return {
        "id": u["id"], "full_name": u["full_name"], "username": u["username"], "email": u["email"],
        "phone": u["phone"], "avatar": u["avatar"], "birth_date": u["birth_date"], "status": u["status"],
        "treatment": u["treatment"], "family_history": bool(u["family_history"]),
        "last_self_exam": u["last_self_exam"], "doctor_id": u["doctor_id"],
        "next_appointment": appt, "last_report": last,
        "unread_messages": query("SELECT COUNT(*) AS n FROM messages WHERE sender_id = ? AND recipient_id = ? "
                                 "AND is_read = 0", (user_id, u["doctor_id"] or 0), one=True)["n"],
    }


def patient_summaries(doctor_id, q=""):
    """Liste des patientes d'un médecin en 1 requête (au lieu de 4 par patiente)."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    rows = query(
        """
        SELECT u.id, u.full_name, u.username, u.email, u.phone, u.avatar, p.birth_date, p.status, p.treatment,
               p.family_history, p.last_self_exam, p.doctor_id,
               r.id AS r_id, r.triage AS r_triage, r.risk_score AS r_score, r.created_at AS r_created, r.reviewed AS r_reviewed,
               a.id AS a_id, a.starts_at AS a_starts, a.kind AS a_kind, a.notes AS a_notes, a.status AS a_status,
               (SELECT COUNT(*) FROM messages m WHERE m.sender_id = u.id AND m.recipient_id = p.doctor_id
                  AND m.is_read = 0) AS unread_messages
        FROM patient_profiles p JOIN users u ON u.id = p.user_id
        LEFT JOIN reports r ON r.id = (SELECT MAX(id) FROM reports WHERE patient_id = u.id)
        LEFT JOIN appointments a ON a.id = (SELECT id FROM appointments WHERE patient_id = u.id AND status = 'prevu'
                                            AND starts_at >= ? ORDER BY starts_at LIMIT 1)
        WHERE p.doctor_id = ? AND (? = '' OR lower(u.full_name) LIKE ? OR lower(u.username) LIKE ?)
        ORDER BY u.full_name
        """, (now, doctor_id, q, f"%{q}%", f"%{q}%"))
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "full_name": r["full_name"], "username": r["username"], "email": r["email"],
            "phone": r["phone"], "avatar": r["avatar"], "birth_date": r["birth_date"], "status": r["status"],
            "treatment": r["treatment"], "family_history": bool(r["family_history"]),
            "last_self_exam": r["last_self_exam"], "doctor_id": r["doctor_id"],
            "last_report": {"id": r["r_id"], "triage": r["r_triage"], "risk_score": r["r_score"],
                            "created_at": r["r_created"], "reviewed": r["r_reviewed"]} if r["r_id"] else None,
            "next_appointment": {"id": r["a_id"], "starts_at": r["a_starts"], "kind": r["a_kind"],
                                 "notes": r["a_notes"], "status": r["a_status"]} if r["a_id"] else None,
            "unread_messages": r["unread_messages"],
        })
    return out


def report_row(r):
    if not r:
        return None
    r = dict(r)
    r["answers"] = loads(r.pop("answers_json"), {})
    r["report"] = loads(r.pop("report_json"), {})
    return r


def conversation(a, b, limit=200):
    return query(
        "SELECT m.*, u.full_name AS sender_name, u.role AS sender_role FROM messages m "
        "JOIN users u ON u.id = m.sender_id WHERE (sender_id = ? AND recipient_id = ?) "
        "OR (sender_id = ? AND recipient_id = ?) ORDER BY m.id DESC LIMIT ?", (a, b, b, a, limit))[::-1]


def send_message(sender, recipient_id, body):
    mid = execute("INSERT INTO messages (sender_id, recipient_id, body) VALUES (?,?,?)",
                  (sender["id"], recipient_id, body))
    events.publish([sender["id"], recipient_id], "message",
                   {"id": mid, "sender_id": sender["id"], "recipient_id": recipient_id})
    link = (f"/doctor/patients/{sender['id']}?tab=messages" if sender["role"] == "patient" else "/doctor-contact")
    notify(recipient_id, "message", f"Nouveau message de {sender['full_name']}", body[:140], link=link, ref_id=mid)
    return mid


__all__ = ["dumps", "loads"]
