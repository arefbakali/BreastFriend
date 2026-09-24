"""Diffusion d'événements temps réel (Server-Sent Events).

Un abonné = un onglet ouvert. Les routes publient après chaque écriture
(message, notification, rendez-vous, compte rendu, document RAG) et le frontend
invalide les données concernées : plus besoin d'actualiser la page.

Implémentation en mémoire, adaptée à un processus unique (serveur Flask threadé,
Waitress). Pour plusieurs processus, remplacer par Redis pub/sub (même interface).
"""
import itertools
import json
import queue
import threading

_lock = threading.Lock()
_subscribers = {}          # id -> (user_id, role, Queue)
_ids = itertools.count(1)


def subscribe(user_id, role):
    q = queue.Queue(maxsize=200)
    with _lock:
        sid = next(_ids)
        _subscribers[sid] = (user_id, role, q)
    return sid, q


def unsubscribe(sid):
    with _lock:
        _subscribers.pop(sid, None)


def _deliver(targets, event, data):
    payload = json.dumps(data, ensure_ascii=False, default=str)
    for q in targets:
        try:
            q.put_nowait((event, payload))
        except queue.Full:       # onglet figé : on ne bloque jamais l'émetteur
            pass


def publish(user_ids, event, data=None):
    ids = {int(u) for u in user_ids if u is not None}
    with _lock:
        targets = [q for uid, _, q in _subscribers.values() if uid in ids]
    _deliver(targets, event, data or {})


def publish_role(role, event, data=None):
    with _lock:
        targets = [q for _, r, q in _subscribers.values() if r == role]
    _deliver(targets, event, data or {})


def subscriber_count():
    with _lock:
        return len(_subscribers)
