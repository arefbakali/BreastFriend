"""Authentification par jeton signé (itsdangerous, fourni avec Flask)."""
from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from database import query


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="bf-auth")


def create_token(user):
    return _serializer().dumps({"uid": user["id"], "role": user["role"]})


def hash_password(pw):
    return generate_password_hash(pw)


def verify_password(pw_hash, pw):
    return check_password_hash(pw_hash, pw)


def public_user(user):
    if not user:
        return None
    return {k: user.get(k) for k in ("id", "username", "role", "full_name", "email", "phone", "specialty", "avatar")}


TICKET_MAX_AGE = 120   # secondes


def create_ticket(user, purpose):
    """Jeton court (2 min) limité à un usage (« pdf », « events ») pour les URL où l'on ne
    peut pas envoyer d'en-tête Authorization (EventSource, lien PDF). Le jeton de session
    long n'apparaît ainsi jamais dans une URL ni dans les journaux du serveur."""
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"bf-ticket-{purpose}").dumps(
        {"uid": user["id"]})


def _identity_from_request(ticket_purpose):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        data = _serializer().loads(header[7:], max_age=current_app.config["TOKEN_MAX_AGE"])
        return data["uid"]
    ticket = request.args.get("ticket")
    if ticket and ticket_purpose and request.method == "GET":
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"bf-ticket-{ticket_purpose}")
        return s.loads(ticket, max_age=TICKET_MAX_AGE)["uid"]
    return None


def login_required(roles=None, ticket=None):
    """ticket : usage autorisé d'un jeton court en paramètre d'URL (GET uniquement)."""
    roles = set([roles] if isinstance(roles, str) else (roles or []))

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                uid = _identity_from_request(ticket)
            except SignatureExpired:
                return jsonify(error="Session expirée, reconnectez-vous."), 401
            except BadSignature:
                return jsonify(error="Jeton invalide."), 401
            if uid is None:
                return jsonify(error="Authentification requise."), 401
            user = query("SELECT * FROM users WHERE id = ?", (uid,), one=True)
            if not user:
                return jsonify(error="Utilisateur introuvable."), 401
            if roles and user["role"] not in roles:
                return jsonify(error="Accès refusé pour ce rôle."), 403
            g.user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator
