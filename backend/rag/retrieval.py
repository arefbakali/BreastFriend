"""Étape 7 : recherche. question -> embedding -> vecteurs (+ BM25) -> fusion -> reranking -> meilleurs passages."""
import logging
import time
from dataclasses import asdict, dataclass, field

from . import keyword_index
from .fusion import rrf
from .text_utils import normalize_query, term_coverage

log = logging.getLogger("breastfriend.rag.retrieval")


@dataclass
class Retrieved:
    chunk_id: str
    document_id: str
    filename: str
    title: str
    section: str | None
    page_start: int | None
    page_end: int | None
    text: str
    scores: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _load_chunks(conn, ids):
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT c.id, c.document_id, c.text, c.section, c.page_start, c.page_end, d.filename, d.status "
        f"FROM rag_chunks c JOIN rag_documents d ON d.id = c.document_id WHERE c.id IN ({marks})", ids).fetchall()
    return {r[0]: r for r in rows if r[7] == "ready"}


def retrieve(conn, cfg, embedder, store, reranker, query, *, candidates=None, final_k=None, titles=None,
             use_reranker=True):
    """Renvoie (passages retenus, informations de diagnostic)."""
    t0 = time.perf_counter()
    candidates = candidates or cfg["RAG_RETRIEVAL_TOP_K"]
    final_k = final_k or cfg["RAG_FINAL_TOP_K"]
    query = normalize_query(query)
    if not query:
        return [], {}

    qvec = embedder.embed_query(query)
    t_embed = time.perf_counter()
    vec_hits = store.search(qvec, candidates)
    vec_scores = {cid: s for cid, s, _ in vec_hits}
    rankings = {"vector": [cid for cid, s, _ in vec_hits if s >= cfg["RAG_MIN_VECTOR_SCORE"] * 0.5]}
    kw_scores = {}
    if cfg.get("RAG_HYBRID"):
        kw = keyword_index.search(conn, query, candidates)
        kw_scores = dict(kw)
        rankings["bm25"] = [cid for cid, _ in kw]
    fused = rrf(rankings)[:candidates]
    rows = _load_chunks(conn, [cid for cid, _, _ in fused])
    pool = []
    for cid, fscore, ranks in fused:
        r = rows.get(cid)
        if not r:          # document supprimé / en cours de réindexation
            continue
        pool.append(Retrieved(cid, r[1], r[6], (titles or {}).get(r[1], r[6]), r[3], r[4], r[5], r[2],
                              {"vector": round(vec_scores.get(cid, 0.0), 4), "bm25": round(kw_scores.get(cid, 0.0), 3),
                               "fused": round(fscore, 5), "ranks": ranks}))
    t_search = time.perf_counter()

    rerank_scores = (reranker.score(query, [f"{p.section or ''}\n{p.text}" for p in pool])
                     if pool and use_reranker else None)
    if rerank_scores is not None:
        for p, s in zip(pool, rerank_scores):
            p.scores["rerank"] = round(float(s), 4)
        pool.sort(key=lambda p: -p.scores["rerank"])
        kept = [p for p in pool if p.scores["rerank"] >= cfg["RAG_MIN_RERANK_SCORE"]]
    else:
        # sans reranker : vraie proximité sémantique, OU fort signal lexical (bien classé en BM25
        # ET couvrant au moins 60 % des termes de la question, avec une similarité non négligeable)
        min_vec = cfg["RAG_MIN_VECTOR_SCORE"]
        for p in pool:
            p.scores["coverage"] = round(term_coverage(query, f"{p.section or ''} {p.text}"), 2)
        kept = [p for p in pool if p.scores["vector"] >= min_vec
                or (p.scores["ranks"].get("bm25", 99) <= 3 and p.scores["coverage"] >= 0.6
                    and p.scores["vector"] >= min_vec * 0.5)]
    t_rerank = time.perf_counter()
    info = {"candidates": len(pool), "kept": min(len(kept), final_k), "reranker": bool(rerank_scores is not None),
            "timings_ms": {"embed": round((t_embed - t0) * 1000), "search": round((t_search - t_embed) * 1000),
                           "rerank": round((t_rerank - t_search) * 1000)}}
    log.info("RAG : %s candidats -> %s retenus (%s)", info["candidates"], info["kept"], info["timings_ms"])
    return kept[:final_k], info
