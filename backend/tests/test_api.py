"""Tests de bout en bout de l'API.   Lancer :  python -m unittest discover -s tests -v"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from tests.fakes import FakeServer  # noqa: E402

AVATAR = BACKEND / "static" / "avatars" / "patient3.jpg"


def test_config(tmp, llm_url, **extra):
    """Configuration de test : embeddings lexicaux déterministes, base vectorielle locale,
    LLM simulé via HTTP (protocole Ollama). Les tests Qdrant / modèles réels sont à part."""
    cfg = {
        "DATA_DIR": tmp, "DATABASE_PATH": tmp / "test.db", "UPLOAD_DIR": tmp / "uploads",
        "DOCUMENTS_DIR": tmp / "documents", "REPORTS_DIR": tmp / "reports",
        "SEED_DEMO_DATA": True, "TESTING": True,
        "EMBEDDING_PROVIDER": "hashing", "VECTOR_DB": "local", "RERANKER_ENABLED": False,
        "LLM_PROVIDER": "ollama", "OLLAMA_BASE_URL": llm_url, "OLLAMA_MODEL": "fake-llm", "LLM_MAX_RETRIES": 1,
    }
    cfg.update(extra)
    return cfg


class BaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.fake = FakeServer()
        cls.app = create_app(test_config(cls.tmp, cls.fake.url))
        cls.rag = cls.app.extensions["rag"]
        cls.rag.wait_ready(60)
        cls.wait_indexed()
        cls.c = cls.app.test_client()

    @classmethod
    def wait_indexed(cls):
        import time
        time.sleep(0.2)
        assert cls.app.extensions["jobs"].wait_idle(120), "indexation trop longue"

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def login(self, username, password="demo1234"):
        r = self.c.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(r.status_code, 200, r.json)
        return {"Authorization": f"Bearer {r.json['token']}"}


class AuthTests(BaseCase):
    def test_login_ok_and_bad(self):
        self.login("dr.amel")
        self.assertEqual(self.c.post("/api/auth/login", json={"username": "dr.amel", "password": "x"}).status_code, 401)

    def test_protected_requires_token(self):
        self.assertEqual(self.c.get("/api/patient/dashboard").status_code, 401)
        self.assertEqual(self.c.get("/api/patient/dashboard", headers={"Authorization": "Bearer faux"}).status_code, 401)

    def test_role_isolation(self):
        self.assertEqual(self.c.get("/api/doctor/patients", headers=self.login("salma")).status_code, 403)
        self.assertEqual(self.c.get("/api/patient/dashboard", headers=self.login("dr.amel")).status_code, 403)

    def test_register_patient_and_doctor(self):
        docs = self.c.get("/api/auth/doctors").json["doctors"]
        r = self.c.post("/api/auth/register", json={"username": "nadia", "password": "secret1", "full_name": "Nadia B",
                                                    "doctor_id": docs[0]["id"]})
        self.assertEqual(r.status_code, 201, r.json)
        self.assertEqual(self.c.post("/api/auth/register", json={"username": "nadia", "password": "secret1",
                                                                 "full_name": "X"}).status_code, 409)
        bad = self.c.post("/api/auth/register", json={"username": "drx", "password": "secret1", "full_name": "Dr X",
                                                      "role": "doctor", "invite_code": "nope"})
        self.assertEqual(bad.status_code, 403)
        ok = self.c.post("/api/auth/register", json={"username": "drx", "password": "secret1", "full_name": "Dr X",
                                                     "role": "doctor", "invite_code": "BF-MEDECIN-2024"})
        self.assertEqual(ok.status_code, 201)


class ChatbotTests(BaseCase):
    def test_rag_answer_with_sources(self):
        h = self.login("salma")
        r = self.c.post("/api/chat", json={"message": "Comment faire mon autopalpation des seins ?"}, headers=h)
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["mode"], "llm")
        self.assertTrue(r.json["cited"])
        self.assertIn("03_autopalpation.md", [s["filename"] for s in r.json["sources"]])
        self.assertNotIn("scores", r.json["sources"][0])          # scores réservés au mode diagnostic

    def test_urgent_detection(self):
        r = self.c.post("/api/chat", json={"message": "J'ai 39 de fièvre pendant ma chimio"}, headers=self.login("meriem"))
        self.assertTrue(r.json["urgent"])
        self.assertIn("190", r.json["answer"])

    def test_out_of_scope(self):
        r = self.c.post("/api/chat", json={"message": "Donne-moi une recette de couscous"}, headers=self.login("salma"))
        self.assertEqual(r.json["mode"], "no_context")
        self.assertEqual(r.json["sources"], [])

    def test_history_and_clear(self):
        h = self.login("ines")
        self.c.post("/api/chat", json={"message": "Bonjour"}, headers=h)
        self.assertGreaterEqual(len(self.c.get("/api/chat/history", headers=h).json["messages"]), 2)
        self.c.delete("/api/chat/history", headers=h)
        self.assertEqual(self.c.get("/api/chat/history", headers=h).json["messages"], [])

    def test_llm_unavailable_is_an_error_not_an_extractive_answer(self):
        h = self.login("salma")
        self.fake.down = True
        try:
            r = self.c.post("/api/chat", json={"message": "Quand choisir une perruque ?"}, headers=h)
        finally:
            self.fake.down = False
        self.assertEqual(r.status_code, 503)
        self.assertIn("indisponible", r.json["error"])
        self.assertNotIn("answer", r.json)

    def test_doctor_uploads_document_to_corpus(self):
        h = self.login("dr.amel")
        doc = (b"# Protocole local\n\n## Consultation infirmiere\n"
               b"La consultation infirmiere d'annonce a lieu le mardi au service zebulon, bureau 12.")
        r = self.c.post("/api/rag/documents", headers=h, data={"file": (io.BytesIO(doc), "protocole.md")},
                        content_type="multipart/form-data")
        self.assertEqual(r.status_code, 202, r.json)
        self.wait_indexed()
        res = self.c.get("/api/rag/search?q=consultation infirmiere zebulon", headers=h).json["results"]
        self.assertEqual(res[0]["filename"], "protocole.md")
        self.assertEqual(self.c.delete(f"/api/rag/documents/{r.json['document']['id']}", headers=h).status_code, 200)

    def test_patient_cannot_manage_knowledge_base(self):
        h = self.login("salma")
        self.assertEqual(self.c.get("/api/rag/documents", headers=h).status_code, 403)
        self.assertEqual(self.c.get("/api/rag/search?q=test", headers=h).status_code, 403)


class FollowUpTests(BaseCase):
    def test_full_questionnaire_flow(self):
        h = self.login("ines")
        q = self.c.get("/api/patient/questionnaire", headers=h).json
        self.assertGreaterEqual(len(q["questions"]), 8)
        answers = {qq["id"]: {"text": "Non."} for qq in q["questions"]}
        lump = next(qq for qq in q["questions"] if qq["category"] == "lump")
        answers[lump["id"]] = {"text": "Oui, une petite boule en haut à droite du sein gauche"}
        r = self.c.post("/api/patient/questionnaire", json={"question_set_id": q["question_set_id"], "answers": answers},
                        headers=h)
        self.assertEqual(r.status_code, 201, r.json)
        self.assertEqual(r.json["triage"]["level"], "a_surveiller")
        rid = r.json["report_id"]

        d = self.login("dr.amel")
        notifs = self.c.get("/api/notifications", headers=d).json["notifications"]
        self.assertTrue(any(n["kind"] == "report" and n["ref_id"] == rid for n in notifs))
        rep = self.c.get(f"/api/doctor/reports/{rid}", headers=d).json["report"]
        self.assertIn("boule", json.dumps(rep["report"], ensure_ascii=False))
        pdf = self.c.get(f"/api/reports/{rid}/pdf", headers=d)
        ticket = self.c.post("/api/tickets", json={"purpose": "pdf"}, headers=d).json["ticket"]
        self.assertTrue(self.c.get(f"/api/reports/{rid}/pdf?ticket={ticket}").data.startswith(b"%PDF"))
        # un jeton de session long n'est plus accepté dans l'URL
        self.assertEqual(self.c.get(f"/api/reports/{rid}/pdf?token={d['Authorization'][7:]}").status_code, 401)
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertEqual(self.c.patch(f"/api/doctor/reports/{rid}", json={"doctor_comment": "RDV la semaine prochaine"},
                                      headers=d).status_code, 200)
        pn = self.c.get("/api/notifications", headers=h).json["notifications"]
        self.assertTrue(any("lu votre compte rendu" in n["title"] for n in pn))
        # une autre patiente ne peut pas lire ce PDF
        self.assertEqual(self.c.get(f"/api/reports/{rid}/pdf", headers=self.login("salma")).status_code, 404)

    def test_seeded_triage(self):
        d = self.login("dr.amel")
        pts = self.c.get("/api/doctor/patients", headers=d).json["patients"]
        self.assertEqual(pts[0]["full_name"], "Meriem Haddad")  # fièvre sous chimio -> prioritaire en tête
        self.assertEqual(pts[0]["last_report"]["triage"], "urgent")
        self.assertEqual(len(self.c.get("/api/doctor/patients?q=leila", headers=d).json["patients"]), 1)

    def test_checkin_notification_and_confirm_questions(self):
        d = self.login("dr.amel")
        notifs = self.c.get("/api/notifications", headers=d).json["notifications"]
        checkin = [n for n in notifs if n["kind"] == "checkin"]
        self.assertTrue(checkin, notifs)
        self.assertTrue(any("Salma" in n["title"] and "2 jours" in n["title"] for n in checkin), checkin)
        salma = next(p for p in self.c.get("/api/doctor/patients", headers=d).json["patients"] if p["username"] == "salma")
        gen = self.c.post(f"/api/doctor/patients/{salma['id']}/questions/generate", headers=d).json["question_set"]
        self.assertTrue(all("rationale" in q for q in gen["questions"]))
        qs = gen["questions"][:5] + [{"category": "pain", "text": "Question ajoutée par le médecin ?"}]
        r = self.c.put(f"/api/doctor/patients/{salma['id']}/questions", json={"questions": qs, "confirm": True}, headers=d)
        self.assertEqual(r.status_code, 200)
        pq = self.c.get("/api/patient/questionnaire", headers=self.login("salma")).json
        self.assertTrue(pq["confirmed"])
        self.assertEqual(pq["questions"][-1]["text"], "Question ajoutée par le médecin ?")

    def test_appointments_notes_messages(self):
        d = self.login("dr.amel")
        pid = self.c.get("/api/doctor/patients?q=leila", headers=d).json["patients"][0]["id"]
        a = self.c.post("/api/doctor/appointments", json={"patient_id": pid, "starts_at": "2030-01-10T10:00",
                                                          "kind": "consultation"}, headers=d)
        self.assertEqual(a.status_code, 201)
        cal = self.c.get("/api/doctor/appointments?from=2030-01-01&to=2030-01-31", headers=d).json["appointments"]
        self.assertEqual(len(cal), 1)
        self.c.patch(f"/api/doctor/appointments/{cal[0]['id']}", json={"status": "annule"}, headers=d)
        self.assertEqual(self.c.put("/api/doctor/notes", json={"body": "Note test"}, headers=d).status_code, 200)
        self.assertEqual(self.c.get("/api/doctor/notes", headers=d).json["note"]["body"], "Note test")
        self.c.put("/api/doctor/notes", json={"body": "Note patiente", "patient_id": pid}, headers=d)
        self.assertEqual(self.c.get(f"/api/doctor/notes?patient_id={pid}", headers=d).json["note"]["body"], "Note patiente")
        p = self.login("leila")
        self.c.post("/api/patient/messages", json={"body": "Merci docteur"}, headers=p)
        msgs = self.c.get(f"/api/doctor/patients/{pid}/messages", headers=d).json["messages"]
        self.assertEqual(msgs[-1]["body"], "Merci docteur")
        self.c.post(f"/api/doctor/patients/{pid}/messages", json={"body": "Avec plaisir"}, headers=d)
        self.assertEqual(self.c.get("/api/patient/messages", headers=p).json["messages"][-1]["body"], "Avec plaisir")

    def test_dashboard_and_self_exam(self):
        h = self.login("salma")
        dash = self.c.get("/api/patient/dashboard", headers=h).json
        self.assertTrue(dash["affirmation"])
        self.assertIsNotNone(dash["next_appointment"])
        r = self.c.post("/api/patient/self-exam", headers=h).json
        self.assertTrue(r["self_exam"]["done_this_month"])
        self.assertFalse(r["self_exam"]["due"])


class WigTests(BaseCase):
    def test_analyze_and_recommend(self):
        h = self.login("meriem")
        prefs = {"color_families": ["brun", "noir"], "length": "mi-long"}
        with open(AVATAR, "rb") as f:
            r = self.c.post("/api/wigs/analyze", headers=h, content_type="multipart/form-data",
                            data={"photo": (f, "moi.jpg"), "preferences": json.dumps(prefs)})
        self.assertEqual(r.status_code, 200, r.json)
        a = r.json["analysis"]
        self.assertIn(a["face_shape"], ["ovale", "rond", "carre", "coeur", "allonge"])
        self.assertTrue(a["annotated_image"].startswith("data:image/jpeg;base64,"))
        items = r.json["recommendations"]["items"]
        self.assertEqual(len(items), 6)
        self.assertIn(items[0]["color_family"], ["brun", "noir"])
        rr = self.c.post("/api/wigs/recommend", headers=h, json={"analysis_id": r.json["id"], "preferences": {
            "face_shape_override": "rond", "color_families": ["blond"], "length": "long"}}).json["recommendations"]
        self.assertEqual(rr["face_shape_used"], "rond")
        self.assertEqual(rr["items"][0]["color_family"], "blond")
        self.assertIsNotNone(self.c.get("/api/wigs/last", headers=h).json["analysis"])

    def test_no_face(self):
        import cv2
        import numpy as np
        ok, buf = cv2.imencode(".jpg", np.full((300, 300, 3), 200, np.uint8))
        r = self.c.post("/api/wigs/analyze", headers=self.login("meriem"), content_type="multipart/form-data",
                        data={"photo": (io.BytesIO(buf.tobytes()), "mur.jpg")})
        self.assertEqual(r.status_code, 422)

    def test_invalid_file(self):
        r = self.c.post("/api/wigs/analyze", headers=self.login("meriem"), content_type="multipart/form-data",
                        data={"photo": (io.BytesIO(b"pas une image"), "x.jpg")})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()


class IsolationTests(BaseCase):
    """Aucune donnée d'une patiente ne doit être accessible à un autre médecin ou à une autre patiente."""

    def test_other_doctor_cannot_touch_patients_reports_or_appointments(self):
        amel, karim = self.login("dr.amel"), self.login("dr.karim")
        pid = self.c.get("/api/doctor/patients?q=salma", headers=amel).json["patients"][0]["id"]
        rid = self.c.get(f"/api/doctor/patients/{pid}", headers=amel).json["reports"][0]["id"]
        appt = self.c.post("/api/doctor/appointments", headers=amel,
                           json={"patient_id": pid, "starts_at": "2031-01-10T09:00", "kind": "consultation"}).json
        aid = appt["appointment"]["id"]
        attempts = [
            ("get", f"/api/doctor/patients/{pid}", None),
            ("put", f"/api/doctor/patients/{pid}", {"status": "remission"}),
            ("get", f"/api/doctor/patients/{pid}/messages", None),
            ("post", f"/api/doctor/patients/{pid}/messages", {"body": "intrusion"}),
            ("post", f"/api/doctor/patients/{pid}/questions/generate", {}),
            ("put", f"/api/doctor/patients/{pid}/questions", {"questions": []}),
            ("get", f"/api/doctor/reports/{rid}", None),
            ("patch", f"/api/doctor/reports/{rid}", {"reviewed": True}),
            ("get", f"/api/reports/{rid}/pdf", None),
            ("patch", f"/api/doctor/appointments/{aid}", {"notes": "x"}),
            ("delete", f"/api/doctor/appointments/{aid}", None),
            ("post", "/api/doctor/appointments", {"patient_id": pid, "starts_at": "2031-01-11T09:00"}),
        ]
        for method, url, body in attempts:
            r = getattr(self.c, method)(url, headers=karim, json=body)
            self.assertIn(r.status_code, (403, 404), f"{method.upper()} {url} -> {r.status_code}")
        self.assertNotIn(pid, [p["id"] for p in self.c.get("/api/doctor/patients", headers=karim).json["patients"]])
        # rien n'a été modifié
        self.assertEqual(self.c.get(f"/api/doctor/patients/{pid}", headers=amel).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/doctor/appointments/{aid}", headers=amel).status_code, 200)

    def test_patient_cannot_read_another_patients_report(self):
        rid = self.c.get("/api/patient/reports", headers=self.login("salma")).json["reports"][0]["id"]
        ines = self.login("ines")
        self.assertEqual(self.c.get(f"/api/patient/reports/{rid}", headers=ines).status_code, 404)
        self.assertEqual(self.c.get(f"/api/reports/{rid}/pdf", headers=ines).status_code, 404)

    def test_event_stream_only_reaches_the_concerned_users(self):
        import events
        sid_k, q_karim = events.subscribe(self.c.get("/api/auth/me", headers=self.login("dr.karim")).json["user"]["id"], "doctor")
        sid_s, q_salma = events.subscribe(self.c.get("/api/auth/me", headers=self.login("salma")).json["user"]["id"], "patient")
        try:
            self.c.post("/api/patient/messages", headers=self.login("salma"), json={"body": "bonjour"})
            names_salma = [q_salma.get_nowait()[0] for _ in range(q_salma.qsize())]
            self.assertIn("message", names_salma)
            self.assertTrue(q_karim.empty(), "un autre médecin ne reçoit rien")
        finally:
            events.unsubscribe(sid_k)
            events.unsubscribe(sid_s)
