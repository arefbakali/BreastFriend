"""Contrat commun des bases vectorielles. Qdrant est testé en mode embarqué (sans Docker)
dès que qdrant-client est installé (pip install -r requirements.txt)."""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag.vectorstore import LocalStore, QdrantStore, collection_name  # noqa: E402

HAS_QDRANT = importlib.util.find_spec("qdrant_client") is not None


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


class StoreContract:
    def make(self, path):
        raise NotImplementedError

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = self.make(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upsert_search_count_delete_persist(self):
        items = [(f"a:{i}", unit([1, i * 0.1, 0, 0]), {"document_id": "a", "page_start": i}) for i in range(3)]
        items += [("b:0", unit([0, 0, 1, 0]), {"document_id": "b", "page_start": 7})]
        self.store.upsert(items)
        self.assertEqual(self.store.count(), 4)
        self.assertEqual(self.store.count("a"), 3)
        hits = self.store.search(unit([0, 0, 1, 0.05]), 2)
        self.assertEqual(hits[0][0], "b:0")
        self.assertEqual(hits[0][2]["page_start"], 7)             # métadonnées liées au vecteur
        self.assertGreater(hits[0][1], hits[1][1])
        self.store.upsert([items[0]])                              # upsert idempotent : pas de doublon
        self.assertEqual(self.store.count(), 4)
        self.assertEqual(self.store.document_ids(), {"a", "b"})
        self.store.delete_document("a")
        self.assertEqual(self.store.count(), 1)
        self.assertTrue(all(h[2]["document_id"] == "b" for h in self.store.search(unit([1, 0, 0, 0]), 5)))
        self.reopen()
        self.assertEqual(self.store.count(), 1)                    # persistance après « redémarrage »

    def test_collection_name_is_model_specific(self):
        self.assertNotEqual(collection_name("bf", "local:BAAI/bge-m3", 1024),
                            collection_name("bf", "openai:text-embedding-3-small", 1536))


class LocalStoreTest(StoreContract, unittest.TestCase):
    def make(self, path):
        return LocalStore("c__test__4", 4, path / "v.db")

    def reopen(self):
        self.store = LocalStore("c__test__4", 4, self.tmp / "v.db")


@unittest.skipUnless(HAS_QDRANT, "qdrant-client non installé")
class QdrantEmbeddedTest(StoreContract, unittest.TestCase):
    def make(self, path):
        return QdrantStore("c__test__4", 4, path=path / "qdrant")

    def reopen(self):
        self.store.client.close()
        self.store = QdrantStore("c__test__4", 4, path=self.tmp / "qdrant")


if __name__ == "__main__":
    unittest.main()
