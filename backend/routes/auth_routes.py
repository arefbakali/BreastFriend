import os

from flask import Blueprint, g, jsonify, request

from auth import create_token, hash_password, login_required, public_user, verify_password
from database import execute, query

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    user = query("SELECT * FROM users WHERE lower(username) = ?", (username,), one=True)
    if not user or not verify_password(user["password_hash"], data.get("password") or ""):
        return jsonify(error="Identifiant ou mot de passe incorrect."), 401
    return jsonify(token=create_token(user), user=public_user(user))


@bp.post("/register")
def register():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    password = d.get("password") or ""
    full_name = (d.get("full_name") or "").strip()
    role = d.get("role") or "patient"
    if len(username) < 3 or len(password) < 6 or not full_name:
        return jsonify(error="Nom complet, identifiant (3+ caractères) et mot de passe (6+ caractères) requis."), 400
    if role not in ("patient", "doctor"):
        return jsonify(error="Rôle invalide."), 400
    if role == "doctor" and d.get("invite_code") != os.getenv("DOCTOR_INVITE_CODE", "BF-MEDECIN-2024"):
        return jsonify(error="Code d'invitation médecin invalide."), 403
    if query("SELECT id FROM users WHERE lower(username) = ?", (username,), one=True):
        return jsonify(error="Cet identifiant est déjà utilisé."), 409
    uid = execute(
        "INSERT INTO users (username, password_hash, role, full_name, email, phone, specialty) VALUES (?,?,?,?,?,?,?)",
        (username, hash_password(password), role, full_name, d.get("email"), d.get("phone"),
         d.get("specialty") if role == "doctor" else None))
    if role == "patient":
        doctor_id = d.get("doctor_id")
        if not doctor_id or not query("SELECT id FROM users WHERE id = ? AND role = 'doctor'", (doctor_id,), one=True):
            first = query("SELECT id FROM users WHERE role = 'doctor' ORDER BY id LIMIT 1", one=True)
            doctor_id = first["id"] if first else None
        execute("INSERT INTO patient_profiles (user_id, doctor_id, birth_date, status, family_history) VALUES (?,?,?,?,?)",
                (uid, doctor_id, d.get("birth_date"), d.get("status") or "prevention", int(bool(d.get("family_history")))))
        if doctor_id:
            from services import notify
            notify(doctor_id, "patient", f"Nouvelle patiente : {full_name}", "Elle vient de rejoindre BreastFriend.",
                   link=f"/doctor/patients/{uid}")
    user = query("SELECT * FROM users WHERE id = ?", (uid,), one=True)
    return jsonify(token=create_token(user), user=public_user(user)), 201


@bp.get("/me")
@login_required()
def me():
    return jsonify(user=public_user(g.user))


@bp.get("/doctors")
def doctors():
    return jsonify(doctors=query("SELECT id, full_name, specialty FROM users WHERE role = 'doctor' ORDER BY full_name"))
