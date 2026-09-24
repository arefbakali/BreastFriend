"""BreastFriend — API Flask.

Lancement : python app.py   (http://127.0.0.1:5000)
"""
import logging
import os
import secrets

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from config import Config
from database import init_db
from jobs import JobQueue
from rag.service import RagService

log = logging.getLogger("breastfriend")


def _secret_key(app):
    """Sans SECRET_KEY, une clé aléatoire est créée une fois et conservée dans DATA_DIR
    (les sessions survivent aux redémarrages, et la clé n'est jamais une valeur par défaut connue)."""
    if os.getenv("SECRET_KEY") or app.config.get("TESTING"):
        return app.config["SECRET_KEY"]
    path = app.config["DATA_DIR"] / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
    return path.read_text().strip()


def create_app(overrides=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    for key in ("DATA_DIR", "UPLOAD_DIR", "DOCUMENTS_DIR", "REPORTS_DIR"):
        app.config[key].mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _secret_key(app)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db(app)

    # Moteur RAG : modèles chargés une fois en arrière-plan ; indexation via une file de tâches
    app.extensions["jobs"] = JobQueue(app)
    app.extensions["rag"] = RagService(app, app.extensions["jobs"])
    app.extensions["rag"].start(sync=app.config["RAG_AUTO_SYNC"])

    from routes import auth_routes, chat_routes, common_routes, doctor_routes, patient_routes
    for mod in (auth_routes, chat_routes, common_routes, doctor_routes, patient_routes):
        app.register_blueprint(mod.bp)

    if app.config.get("SEED_DEMO_DATA"):
        from seed import seed_if_empty
        with app.app_context():
            seed_if_empty()

    allowed = {o.strip() for o in app.config["CORS_ORIGINS"].split(",") if o.strip()}

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # la caméra n'est autorisée que pour l'application elle-même
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return cors(resp)

    def cors(resp):
        origin = request.headers.get("Origin")
        if origin and (origin in allowed or "*" in allowed):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        return resp

    @app.route("/api/<path:_any>", methods=["OPTIONS"])
    def preflight(_any):
        return "", 204

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(app.config["STATIC_DIR"], filename, max_age=3600)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify(error=f"Fichier trop volumineux ({mb} Mo maximum)."), 413

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception("Erreur serveur")
        return jsonify(error="Erreur interne du serveur."), 500

    # Sert le frontend React compilé (npm run build) : une seule URL en production
    dist = app.config["FRONTEND_DIST"]

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            return jsonify(error="Route inconnue."), 404
        if not dist.exists():
            return ("<h3>API BreastFriend en ligne.</h3><p>Lancez le frontend : <code>cd frontend && npm run dev</code> "
                    "puis ouvrez <a href='http://localhost:5173'>http://localhost:5173</a>.</p>"), 200
        target = dist / path
        if path and target.is_file():
            return send_from_directory(dist, path)
        return send_from_directory(dist, "index.html")

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.getenv("PORT", 5000))
    print(f"\n  BreastFriend API -> http://127.0.0.1:{port}   (LLM : {application.config['LLM_PROVIDER']}, "
          f"embeddings : {application.config['EMBEDDING_PROVIDER']}, base vectorielle : {application.config['VECTOR_DB']})\n")
    # threaded : les flux temps réel (SSE) et les réponses en streaming ne bloquent pas les autres requêtes.
    # use_reloader=False : le rechargement automatique lancerait un 2e processus (modèles chargés deux fois,
    # verrou du Qdrant embarqué).
    application.run(host=os.getenv("HOST", "127.0.0.1"), port=port, debug=os.getenv("FLASK_DEBUG") == "1",
                    threaded=True, use_reloader=False)
