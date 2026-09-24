"""Accès SQLite (bibliothèque standard, aucune dépendance ORM)."""
import json
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor')),
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    specialty TEXT,
    avatar TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS patient_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES users(id),
    birth_date TEXT,
    status TEXT DEFAULT 'prevention',      -- prevention | traitement | remission
    treatment TEXT,
    family_history INTEGER DEFAULT 0,
    last_self_exam TEXT,
    reminder_day INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doctor_id INTEGER NOT NULL REFERENCES users(id),
    starts_at TEXT NOT NULL,
    kind TEXT DEFAULT 'consultation',     -- consultation | check-in | mammographie
    notes TEXT,
    status TEXT DEFAULT 'prevu'           -- prevu | fait | annule
);

CREATE TABLE IF NOT EXISTS question_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES users(id),
    questions_json TEXT NOT NULL,
    source TEXT DEFAULT 'bank',           -- bank | rag | rag+llm | doctor
    confirmed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES users(id),
    question_set_id INTEGER REFERENCES question_sets(id),
    answers_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    triage TEXT NOT NULL,                 -- rassurant | a_surveiller | urgent
    risk_score INTEGER DEFAULT 0,
    reviewed INTEGER DEFAULT 0,
    doctor_comment TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                   -- report | checkin | message | appointment
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    ref_id INTEGER,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doctor_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (doctor_id, patient_id)
);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                   -- user | assistant
    content TEXT NOT NULL,
    sources_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wig_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_json TEXT NOT NULL,
    preferences_json TEXT,
    recommendations_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS self_exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    done_at TEXT DEFAULT (datetime('now'))
);
"""


# Migrations versionnées (PRAGMA user_version). Chaque étape est idempotente et
# ne supprime aucune donnée : une base existante est mise à niveau au démarrage.
MIGRATIONS = [
    # v1 : schéma initial (SCHEMA ci-dessus)
    lambda c: c.executescript(SCHEMA),
    # v2 : index sur les colonnes filtrées / jointes (supprime des scans complets)
    lambda c: c.executescript("""
        CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id, is_read, id);
        CREATE INDEX IF NOT EXISTS ix_notifications_ref ON notifications(user_id, kind, ref_id);
        CREATE INDEX IF NOT EXISTS ix_messages_pair ON messages(sender_id, recipient_id, id);
        CREATE INDEX IF NOT EXISTS ix_messages_recipient ON messages(recipient_id, is_read);
        CREATE INDEX IF NOT EXISTS ix_reports_patient ON reports(patient_id, id);
        CREATE INDEX IF NOT EXISTS ix_reports_doctor ON reports(doctor_id, reviewed, id);
        CREATE INDEX IF NOT EXISTS ix_appointments_doctor ON appointments(doctor_id, starts_at);
        CREATE INDEX IF NOT EXISTS ix_appointments_patient ON appointments(patient_id, starts_at);
        CREATE INDEX IF NOT EXISTS ix_profiles_doctor ON patient_profiles(doctor_id);
        CREATE INDEX IF NOT EXISTS ix_question_sets_patient ON question_sets(patient_id, confirmed, id);
        CREATE INDEX IF NOT EXISTS ix_chat_history_user ON chat_history(user_id, id);
    """),
    # v3 : registre documentaire du RAG + chunks + index plein texte BM25 (FTS5)
    lambda c: c.executescript("""
        CREATE TABLE IF NOT EXISTS rag_documents (
            id TEXT PRIMARY KEY,                 -- identifiant stable (uuid)
            filename TEXT NOT NULL,              -- nom du fichier déposé
            title TEXT,                          -- titre détecté (Markdown # / nom de fichier)
            stored_path TEXT NOT NULL,           -- chemin relatif sous DATA_DIR (ou corpus intégré)
            source_type TEXT NOT NULL,           -- pdf | md | txt
            origin TEXT NOT NULL DEFAULT 'upload',   -- upload | builtin
            checksum TEXT NOT NULL UNIQUE,       -- sha256 du contenu : anti-doublons
            size_bytes INTEGER,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded | processing | embedding | indexing | ready | failed
            progress REAL DEFAULT 0,
            error TEXT,
            pages INTEGER,
            ocr_pages INTEGER DEFAULT 0,
            empty_pages INTEGER DEFAULT 0,
            chunks INTEGER DEFAULT 0,
            index_fingerprint TEXT,              -- modèle d'embedding + paramètres de découpage utilisés
            created_at TEXT DEFAULT (datetime('now')),
            indexed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id TEXT PRIMARY KEY,                 -- <document_id>:<ordinal>
            document_id TEXT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            section TEXT,
            page_start INTEGER,
            page_end INTEGER,
            tokens INTEGER
        );
        CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc ON rag_chunks(document_id, ordinal);
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
            chunk_id UNINDEXED, section, text, tokenize = 'unicode61 remove_diacritics 2'
        );
    """),
]


def _connect(path):
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def connect(path):
    """Connexion hors requête Flask (tâches d'arrière-plan). À fermer par l'appelant."""
    return _connect(path)


@contextmanager
def session(path):
    """Connexion courte : commit si tout va bien, rollback sinon, toujours fermée."""
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, step in enumerate(MIGRATIONS[version:], start=version + 1):
        step(conn)
        conn.execute(f"PRAGMA user_version = {i}")
        conn.commit()
    return conn.execute("PRAGMA user_version").fetchone()[0]


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.config["DATABASE_PATH"].parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(app.config["DATABASE_PATH"])
    # WAL : lectures concurrentes pendant qu'une tâche d'indexation écrit
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    conn.close()
    app.teardown_appcontext(close_db)


def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


@contextmanager
def transaction():
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def loads(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dumps(value):
    return json.dumps(value, ensure_ascii=False)
