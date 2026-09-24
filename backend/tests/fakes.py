"""Serveur HTTP de test qui reproduit les protocoles réels :
  OpenAI Responses (/v1/responses), OpenAI-compatible (/v1/chat/completions),
  Ollama (/api/chat, /api/embed), OpenAI embeddings (/v1/embeddings) — avec streaming.

Le « modèle » simulé est volontairement simple et vérifiable : il répond avec une
phrase de la source qui recouvre le mieux la question, suivie de son numéro [n],
ou déclare l'information introuvable si aucune source ne correspond.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag.embeddings import HashingEmbeddings
from rag.text_utils import keyword_terms

_emb = HashingEmbeddings(dim=384)


def fake_answer(prompt):
    m = re.search(r"QUESTION DE LA PERSONNE :\s*(.+?)\n\nRéponds", prompt, re.S)
    question = m.group(1) if m else prompt
    terms = set(keyword_terms(question))
    best, best_n, best_score = None, None, 0
    for n, body in re.findall(r'<source id="(\d+)">\n(.*?)\n</source>', prompt, re.S):
        for sent in re.split(r"(?<=[.!?])\s+", body):
            score = len(terms & set(keyword_terms(sent)))
            if score > best_score:
                best, best_n, best_score = sent.strip(), n, score
    if best_score < 2:
        return "Je n'ai pas trouvé cette information dans les documents de BreastFriend."
    return f"D'après les documents : {best} [{best_n}]"


class FakeServer:
    def __init__(self, port=0):
        self.requests = []
        self.fail = 0            # nombre de réponses 503 à renvoyer avant de répondre
        self.down = False        # 503 permanent
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _stream(self, ctype, chunks):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                for c in chunks:
                    self.wfile.write(c.encode())
                    self.wfile.flush()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                server.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                if server.down or server.fail > 0:
                    server.fail = max(0, server.fail - 1)
                    return self._json(503, {"error": {"message": "overloaded"}})
                p = self.path
                if p.endswith("/embeddings"):
                    vecs = _emb._embed(body["input"])
                    return self._json(200, {"data": [{"index": i, "embedding": v.tolist()} for i, v in enumerate(vecs)]})
                if p.endswith("/api/embed"):
                    return self._json(200, {"embeddings": _emb._embed(body["input"]).tolist()})
                if p.endswith("/responses"):
                    prompt = "\n".join(m["content"] for m in body["input"])
                    text = fake_answer(prompt)
                    if body.get("stream"):
                        words = re.findall(r"\S+\s*", text)
                        evs = [f"event: response.output_text.delta\ndata: {json.dumps({'type': 'response.output_text.delta', 'delta': w})}\n\n"
                               for w in words]
                        evs.append('event: response.completed\ndata: {"type":"response.completed"}\n\n')
                        return self._stream("text/event-stream", evs)
                    return self._json(200, {"status": "completed", "output": [
                        {"type": "reasoning", "summary": []},
                        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]})
                if p.endswith("/chat/completions") or p.endswith("/api/chat"):
                    prompt = "\n".join(m["content"] for m in body["messages"])
                    if body.get("format") == "json" or body.get("response_format"):
                        text = '{"questions": []}'
                    else:
                        text = fake_answer(prompt)
                    ollama = p.endswith("/api/chat")
                    if body.get("stream"):
                        words = re.findall(r"\S+\s*", text)
                        if ollama:
                            lines = [json.dumps({"message": {"content": w}, "done": False}) + "\n" for w in words]
                            lines.append(json.dumps({"message": {"content": ""}, "done": True}) + "\n")
                            return self._stream("application/x-ndjson", lines)
                        evs = [f"data: {json.dumps({'choices': [{'delta': {'content': w}}]})}\n\n" for w in words]
                        evs.append("data: [DONE]\n\n")
                        return self._stream("text/event-stream", evs)
                    if ollama:
                        return self._json(200, {"message": {"role": "assistant", "content": text}, "done": True})
                    return self._json(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})
                return self._json(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def last(self, suffix):
        return next(r for r in reversed(self.requests) if r["path"].endswith(suffix))

    def close(self):
        self.httpd.shutdown()
