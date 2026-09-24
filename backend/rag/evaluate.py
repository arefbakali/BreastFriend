"""Évaluation du RAG sur rag/eval/dataset.json (et sur des éléments supplémentaires).

    python -m rag.evaluate              # recherche seule (rapide, sans LLM)
    python -m rag.evaluate --with-llm   # + réponses du LLM configuré : citations, faits, ancrage

Mesures :
  hit@k            la source attendue figure dans les k passages retenus
  section@k        la section attendue figure dans les k passages retenus
  MRR              rang réciproque moyen de la source attendue
  rejet            questions sans réponse : aucun passage retenu (ou réponse « introuvable »)
  citations        (LLM) la réponse cite la source attendue
  faits clés       (LLM) proportion des faits attendus présents dans la réponse
  ancrage          (LLM) phrases factuelles portant une citation dont la source partage leurs termes
"""
import argparse
import json
import re
import sys
from pathlib import Path

from .text_utils import fold, keyword_terms

DATASET = Path(__file__).with_name("eval") / "dataset.json"


def _sentences(text):
    text = re.sub(r"_[^_]+_$", "", text.strip())          # avertissement final
    # « phrase. [2] » : la citation placée après le point appartient à la phrase qui précède
    text = re.sub(r"([.!?])\s*((?:\[\d+\])+)", r" \2\1", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 25]


def groundedness(answer, sources):
    by_n = {s["n"]: s["excerpt"] for s in sources}
    factual = [s for s in _sentences(answer) if not re.search(r"n'ai pas trouvé|urgences \(SAMU", s)]
    if not factual:
        return None
    ok = 0
    for s in factual:
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", s) if int(n) in by_n]
        terms = set(keyword_terms(s))
        if cited and terms and any(len(terms & set(keyword_terms(by_n[n]))) / len(terms) >= 0.3 for n in cited):
            ok += 1
    return ok / len(factual)


def run(app, items, k=None, with_llm=False):
    from rag import chat_service
    rag = app.extensions["rag"]
    cfg = app.config
    k = k or cfg["RAG_FINAL_TOP_K"]
    rows = []
    for it in items:
        passages, info = rag.search(it["question"], final_k=k)
        files = [p.filename for p in passages]
        row = {"id": it["id"], "question": it["question"], "retrieved": files[:k],
               "top": (passages[0].scores if passages else None)}
        if it.get("answerable", True):
            rank = next((i + 1 for i, f in enumerate(files) if f == it["expected_file"]), None)
            row.update(hit=rank is not None, rr=1 / rank if rank else 0.0,
                       section_hit=any(p.filename == it["expected_file"] and it.get("expected_section", "") in (p.section or "")
                                       for p in passages),
                       page_hit=(None if "expected_page" not in it else any(
                           p.filename == it["expected_file"] and p.page_start is not None
                           and p.page_start <= it["expected_page"] <= (p.page_end or p.page_start) for p in passages)))
        else:
            row["rejected"] = not passages
        if with_llm:
            try:
                res = chat_service.answer(rag, cfg, it["question"], [])
                ans = res["answer"]
                row["answer"] = ans
                cited_files = {s["filename"] for s in res["sources"] if s["n"] in res.get("cited", [])}
                if it.get("answerable", True):
                    row["citation_ok"] = it["expected_file"] in cited_files
                    facts = it.get("key_facts", [])
                    row["facts"] = (sum(fold(f) in fold(ans) for f in facts) / len(facts)) if facts else None
                    row["grounded"] = groundedness(ans, res["sources"])
                else:
                    row["rejected_llm"] = res["mode"] == "no_context" or "pas trouvé" in fold(ans)
            except chat_service.ChatError as exc:
                row["error"] = str(exc)
        rows.append(row)

    def mean(key, subset=None):
        vals = [r[key] for r in (subset or rows) if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    answerable = [r for r in rows if "hit" in r]
    summary = {"k": k, "n": len(rows), "hit@k": mean("hit", answerable), "section@k": mean("section_hit", answerable),
               "page@k": mean("page_hit", answerable), "MRR": mean("rr", answerable),
               "rejection": mean("rejected", [r for r in rows if "rejected" in r]),
               "embedding": rag.embedder.fingerprint, "reranker": getattr(rag.reranker, "model", None),
               "vector_db": rag.store.backend}
    if with_llm:
        summary.update({"citation_correct": mean("citation_ok", answerable), "key_facts": mean("facts", answerable),
                        "groundedness": mean("grounded", answerable),
                        "rejection_llm": mean("rejected_llm", [r for r in rows if "rejected_llm" in r]),
                        "errors": sum(1 for r in rows if "error" in r)})
    return summary, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-llm", action="store_true")
    ap.add_argument("--k", type=int)
    ap.add_argument("--out", default=None, help="fichier JSON du rapport détaillé")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import create_app
    app = create_app({"SEED_DEMO_DATA": False})
    rag = app.extensions["rag"]
    rag.wait_ready(timeout=900)
    app.extensions["jobs"].wait_idle(timeout=3600)
    items = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
    summary, rows = run(app, items, args.k, args.with_llm)
    for r in rows:
        mark = ("OK " if r.get("hit") else "RATÉ") if "hit" in r else ("OK " if r.get("rejected") else "BRUIT")
        top = r["top"] or {}
        print(f"{mark} {r['id']}  vec={top.get('vector', '-')!s:<7} rerank={top.get('rerank', '-')!s:<7} "
              f"{r['question'][:60]}  -> {r['retrieved'][:2]}")
    print("\nRÉSUMÉ :", json.dumps(summary, ensure_ascii=False, indent=2))
    out = Path(args.out) if args.out else app.config["DATA_DIR"] / "eval_report.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rapport détaillé : {out}")


if __name__ == "__main__":
    main()
