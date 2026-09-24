"""File de tâches d'arrière-plan (indexation des documents).

Un seul worker : les documents sont traités l'un après l'autre (mémoire maîtrisée,
pas d'écritures concurrentes dans la base vectorielle). Les requêtes HTTP ne sont
jamais bloquées par une indexation.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("breastfriend.jobs")


class JobQueue:
    def __init__(self, app, workers=1):
        self.app = app
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bf-job")
        self._pending = set()
        self._lock = threading.Lock()

    def submit(self, key, fn, *args):
        """Ignore une tâche identique déjà en attente (clé = identifiant du document)."""
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)

        def run():
            try:
                with self.app.app_context():
                    fn(*args)
            except Exception:
                log.exception("Tâche %s en échec", key)
            finally:
                with self._lock:
                    self._pending.discard(key)

        self._pool.submit(run)
        return True

    def pending(self):
        with self._lock:
            return set(self._pending)

    def wait_idle(self, timeout=60):
        """Utilisé par les tests et le script d'évaluation."""
        import time
        end = time.time() + timeout
        while time.time() < end:
            if not self.pending():
                return True
            time.sleep(0.05)
        return False
