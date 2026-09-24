"""Fusion de classements par Reciprocal Rank Fusion (Cormack et al., 2009).

On combine des RANGS et non des scores bruts : un cosinus (0..1) et un score
BM25 (non borné) ne sont pas comparables entre eux.
"""


def rrf(rankings, k=60, weights=None):
    """rankings : {nom: [chunk_id, ...] dans l'ordre} -> [(chunk_id, score, {nom: rang})]"""
    weights = weights or {}
    scores, ranks = {}, {}
    for name, ids in rankings.items():
        w = weights.get(name, 1.0)
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
            ranks.setdefault(cid, {})[name] = rank
    return sorted(((cid, s, ranks[cid]) for cid, s in scores.items()), key=lambda x: -x[1])
