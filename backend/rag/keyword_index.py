"""Recherche lexicale BM25 via SQLite FTS5 (persistante, incrémentale, sans dépendance).

Complète la recherche vectorielle sur les termes exacts (noms de médicaments,
« BI-RADS 4 », « tamoxifène ») que les embeddings rapprochent parfois mal.
"""
from .text_utils import keyword_terms


def index_chunks(conn, rows):
    """rows : [(chunk_id, section, text)]"""
    conn.executemany("INSERT INTO rag_chunks_fts (chunk_id, section, text) VALUES (?,?,?)", rows)


def delete_document(conn, document_id):
    conn.execute("DELETE FROM rag_chunks_fts WHERE chunk_id IN (SELECT id FROM rag_chunks WHERE document_id = ?)",
                 (document_id,))


def search(conn, query, k):
    terms = keyword_terms(query)
    if not terms:
        return []
    # termes en OR, préfixe (« chimio* » trouve « chimiothérapie ») pour les mots de 4+ lettres
    match = " OR ".join(f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in terms)
    rows = conn.execute(
        "SELECT f.chunk_id, bm25(rag_chunks_fts, 0.0, 2.0, 1.0) AS s FROM rag_chunks_fts f "
        "JOIN rag_chunks c ON c.id = f.chunk_id JOIN rag_documents d ON d.id = c.document_id "
        "WHERE rag_chunks_fts MATCH ? AND d.status = 'ready' ORDER BY s LIMIT ?", (match, k)).fetchall()
    return [(r[0], -float(r[1])) for r in rows]     # bm25() : plus petit = meilleur
