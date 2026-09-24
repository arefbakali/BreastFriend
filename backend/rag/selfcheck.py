"""Vérifie, sur VOTRE machine, les composants réels configurés dans backend/.env :
modèle d'embedding, reranker, base vectorielle (Qdrant), LLM (génération + streaming), OCR.

    python -m rag.selfcheck
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from config import Config
    import llm
    from rag.embeddings import get_embedder
    from rag.extraction import _ocr_available
    from rag.reranker import get_reranker
    from rag.vectorstore import LocalStore, QdrantStore

    cfg = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
    ok = True

    def step(name, fn):
        nonlocal ok
        t0 = time.perf_counter()
        try:
            detail = fn()
            print(f"  OK    {name:<34} {time.perf_counter() - t0:6.2f}s  {detail or ''}")
        except Exception as exc:
            ok = False
            print(f"  ÉCHEC {name:<34} {exc.__class__.__name__}: {exc}")

    print(f"LOCAL_ONLY={cfg['LOCAL_ONLY']}\n")
    state = {}

    def embed():
        emb = get_embedder(cfg)
        a, b, c = emb.embed_documents(["La fièvre pendant la chimiothérapie est une urgence.",
                                       "Choisir une perruque selon la forme du visage.",
                                       "Le train pour Sousse part à 8 heures."])
        q = emb.embed_query("Que faire si j'ai de la fièvre sous chimio ?")
        state["emb"] = emb
        sims = (float(q @ a), float(q @ b), float(q @ c))
        assert sims[0] > max(sims[1:]), f"similarités incohérentes {sims}"
        return f"{emb.fingerprint}, dim={emb.dim}, cos pertinent={sims[0]:.2f} / hors sujet={sims[2]:.2f}"

    def rerank():
        r = get_reranker(cfg)
        if not r.enabled:
            return "désactivé (RERANKER_ENABLED=false)"
        s = r.score("fièvre sous chimiothérapie", ["La fièvre pendant la chimiothérapie est une urgence.",
                                                   "Le train pour Sousse part à 8 heures."])
        assert s[0] > s[1], f"scores {s}"
        return f"{r.model} pertinent={s[0]:.3f} hors sujet={s[1]:.3f}"

    def vectors():
        emb = state["emb"]
        name = f"selfcheck__{uuid.uuid4().hex[:8]}__{emb.dim}"
        store = (QdrantStore(name, emb.dim, cfg["QDRANT_URL"], cfg["QDRANT_API_KEY"], cfg["QDRANT_PATH"])
                 if cfg["VECTOR_DB"] == "qdrant" else LocalStore(name, emb.dim, cfg["DATA_DIR"] / "selfcheck.db"))
        v = emb.embed_documents(["passage de test"])[0]
        store.upsert([("t:0", v, {"document_id": "t", "page_start": 3})])
        hit = store.search(v, 1)[0]
        assert hit[0] == "t:0" and hit[2]["page_start"] == 3
        store.delete_document("t")
        assert store.count() == 0
        if cfg["VECTOR_DB"] == "qdrant":
            store.client.delete_collection(name)
        return f"{cfg['VECTOR_DB']} @ {store.location}"

    def generate():
        p = llm.get_provider(cfg)
        if p is None:
            raise RuntimeError("LLM_PROVIDER=none : le chatbot ne pourra pas répondre")
        text = p.generate([{"role": "system", "content": "Réponds en un mot."},
                           {"role": "user", "content": "Capitale de la Tunisie ?"}], max_tokens=20)
        pieces = list(p.stream([{"role": "user", "content": "Dis bonjour en français."}], max_tokens=20))
        assert pieces, "streaming vide"
        return f"{p.name}/{p.model} -> « {text[:30]} » ; stream {len(pieces)} fragments" + \
               ("  [DONNÉES ENVOYÉES À UN SERVICE EXTERNE]" if p.remote else "")

    step("Embeddings", embed)
    step("Reranker", rerank)
    if "emb" in state:
        step("Base vectorielle", vectors)
    step("LLM", generate)
    step("OCR (Tesseract + Poppler)", lambda: "disponible" if _ocr_available() else
         (_ for _ in ()).throw(RuntimeError("absent : les PDF scannés échoueront (facultatif)")))
    print("\nTout est opérationnel." if ok else "\nCertains composants ne sont pas prêts (voir ci-dessus).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
