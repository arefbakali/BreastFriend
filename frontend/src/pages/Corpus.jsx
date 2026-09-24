import React, { useRef, useState } from "react";
import { api, upload } from "../api.js";
import { useRealtimeEvent } from "../lib/realtime.jsx";
import { invalidate } from "../lib/query.js";
import { ErrorBox, Skeleton, toast, useFetch } from "../components/ui.jsx";
import { fmtDate } from "../utils.js";

const STATUS = {
  uploaded: ["En file d'attente", "st-uploaded"],
  processing: ["Extraction du texte…", "st-busy"],
  embedding: ["Création des embeddings…", "st-busy"],
  indexing: ["Indexation…", "st-busy"],
  ready: ["Prêt", "st-ready"],
  failed: ["Échec", "st-failed"],
};
const BUSY = new Set(["uploaded", "processing", "embedding", "indexing"]);

function StatusPill({ doc }) {
  const [label, cls] = STATUS[doc.status] || [doc.status, ""];
  return (
    <div className="stack-xs">
      <span className={`pill ${cls}`}>{label}{doc.status === "embedding" ? ` ${Math.round((doc.progress || 0) * 100)} %` : ""}</span>
      {BUSY.has(doc.status) && (
        <div className={`progress ${doc.status === "uploaded" ? "indeterminate" : ""}`} aria-hidden="true">
          <span style={{ width: `${Math.max(5, (doc.progress || 0) * 100)}%` }} />
        </div>
      )}
      {doc.status === "failed" && doc.error && <span className="tiny form-error">{doc.error}</span>}
    </div>
  );
}

function EngineCard({ status }) {
  const rag = status?.rag;
  const llm = status?.llm;
  if (!rag) return <section className="card"><Skeleton lines={3} /></section>;
  return (
    <section className="card">
      <h3>Moteur RAG</h3>
      <p className="small">
        État : <strong>{rag.state === "ready" ? "prêt" : rag.state === "loading" ? "chargement des modèles…" : "erreur"}</strong>
        {rag.error && <span className="form-error"> — {rag.error}</span>}
      </p>
      <ul className="plain small">
        <li>Embeddings : <strong>{rag.embedding.model || "—"}</strong> ({rag.embedding.provider}){rag.embedding.remote && " — service externe"}</li>
        <li>Base vectorielle : <strong>{rag.vector_db}</strong>{rag.hybrid ? " + BM25 (recherche hybride, fusion RRF)" : ""}</li>
        <li>Reranker : <strong>{rag.reranker || "désactivé"}</strong></li>
        <li>Génération : {llm?.enabled ? <><strong>{llm.model}</strong> ({llm.provider}){llm.data_leaves_device && " — données envoyées à un service externe"}</> : <span className="form-error">aucun LLM configuré{llm?.error ? ` (${llm.error})` : ""}</span>}</li>
        <li><strong>{rag.ready_documents}</strong> documents prêts · <strong>{rag.chunks}</strong> passages indexés</li>
      </ul>
    </section>
  );
}

function Uploader({ maxMb }) {
  const [items, setItems] = useState([]);   // {name, progress, state, error}
  const input = useRef(null);
  const send = async (files) => {
    for (const file of files) {
      if (file.size > maxMb * 1024 * 1024) {
        setItems((l) => [...l, { name: file.name, state: "error", error: `Fichier trop volumineux (${maxMb} Mo maximum).` }]);
        continue;
      }
      const key = `${file.name}-${Date.now()}`;
      setItems((l) => [...l, { key, name: file.name, progress: 0, state: "uploading" }]);
      const set = (patch) => setItems((l) => l.map((x) => (x.key === key ? { ...x, ...patch } : x)));
      const form = new FormData();
      form.append("file", file);
      try {
        await upload("/rag/documents", form, (p) => set({ progress: p }));
        set({ state: "done", progress: 1 });
        setTimeout(() => setItems((l) => l.filter((x) => x.key !== key)), 2500);
      } catch (e) {
        set({ state: "error", error: e.message });
      }
    }
  };
  return (
    <section className="card">
      <h3>Ajouter des documents</h3>
      <p className="small">PDF, Markdown ou texte (≤ {maxMb} Mo). L'extraction, le découpage, les embeddings et l'indexation se font en arrière-plan : le document devient interrogeable dès qu'il est « Prêt », sans redémarrage.</p>
      <div className="dropzone" onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); send([...e.dataTransfer.files]); }}>
        <button className="btn primary" onClick={() => input.current.click()}>Choisir des fichiers</button>
        <span className="muted small"> ou glissez-les ici</span>
        <input ref={input} type="file" multiple accept=".pdf,.md,.markdown,.txt" hidden
          onChange={(e) => { send([...e.target.files]); e.target.value = ""; }} />
      </div>
      {items.map((it) => (
        <div key={it.key || it.name} className="upload-row">
          <span className="small">{it.name}</span>
          {it.state === "uploading" && <><div className="progress"><span style={{ width: `${Math.round(it.progress * 100)}%` }} /></div><span className="tiny">Envoi… {Math.round(it.progress * 100)} %</span></>}
          {it.state === "done" && <span className="tiny">Envoyé — traitement en cours ci-dessous</span>}
          {it.state === "error" && <span className="tiny form-error">{it.error}</span>}
        </div>
      ))}
    </section>
  );
}

function DocumentDetail({ id, onClose }) {
  const { data, error } = useFetch(`/rag/documents/${id}`);
  return (
    <section className="card">
      <div className="row-between"><h3>Passages indexés</h3><button className="link small" onClick={onClose}>Fermer</button></div>
      {error && <ErrorBox message={error} />}
      {!data ? <Skeleton lines={4} /> : (
        <>
          <p className="small"><strong>{data.document.filename}</strong> · {data.chunks.length} passages</p>
          <div className="chunk-list">
            {data.chunks.map((c) => (
              <div className="chunk" key={c.id}>
                <div className="meta">
                  <span>#{c.ordinal}</span>
                  {c.page_start && <span>page {c.page_start}{c.page_end !== c.page_start ? `–${c.page_end}` : ""}</span>}
                  {c.section && <span>{c.section}</span>}
                  <span>~{c.tokens} tokens</span>
                </div>
                {c.preview}{c.preview.length >= 400 ? "…" : ""}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function SearchTester() {
  const [q, setQ] = useState("");
  const [debug, setDebug] = useState(true);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const run = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api(`/rag/search?q=${encodeURIComponent(q)}&k=8`));
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h3>Tester une question</h3>
      <form onSubmit={run} className="inline-form">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ex : que faire en cas de lymphœdème ?" aria-label="Question de test" />
        <button className="btn ghost" disabled={busy}>{busy ? "Recherche…" : "Rechercher"}</button>
      </form>
      <label className="small check"><input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} /> Afficher les scores (diagnostic)</label>
      {err && <ErrorBox message={err} />}
      {res && (
        <>
          {debug && res.retrieval?.timings_ms && (
            <p className="scores">{res.retrieval.candidates} candidats → {res.retrieval.kept} retenus · embedding {res.retrieval.timings_ms.embed} ms · recherche {res.retrieval.timings_ms.search} ms · reranking {res.retrieval.timings_ms.rerank} ms</p>
          )}
          {res.results.length === 0 && <p className="muted small">Aucun passage suffisamment pertinent : l'assistante répondrait qu'elle n'a pas trouvé l'information.</p>}
          <ol className="search-results">
            {res.results.map((r) => (
              <li key={r.chunk_id}>
                <strong>{r.filename}</strong>{r.page_start ? ` — page ${r.page_start}` : ""}{r.section ? ` · ${r.section}` : ""}
                {debug && (
                  <div className="scores">
                    cosinus {r.scores.vector} · bm25 {r.scores.bm25} · rangs {JSON.stringify(r.scores.ranks)}
                    {r.scores.rerank !== undefined && ` · rerank ${r.scores.rerank}`}{r.scores.coverage !== undefined && ` · couverture ${r.scores.coverage}`}
                  </div>
                )}
                <p className="small">{r.text.slice(0, 320)}{r.text.length > 320 ? "…" : ""}</p>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

export default function Corpus() {
  const { data, error, loading, reload, setData } = useFetch("/rag/documents");
  const status = useFetch("/rag/status");
  const [detail, setDetail] = useState(null);

  // chaque étape du pipeline est poussée par le serveur : mise à jour de la ligne concernée
  useRealtimeEvent("rag_document", (doc) => {
    setData((d) => {
      if (!d) return d;
      if (doc.deleted) return { ...d, documents: d.documents.filter((x) => x.id !== doc.id) };
      const exists = d.documents.some((x) => x.id === doc.id);
      return { ...d, documents: exists ? d.documents.map((x) => (x.id === doc.id ? doc : x)) : [doc, ...d.documents] };
    });
    if (doc.deleted || doc.status === "ready" || doc.status === "failed") invalidate("/rag/status");
  });

  if (loading) return <div className="stack"><Skeleton lines={6} /></div>;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;

  const act = async (fn, okMsg) => {
    try { await fn(); if (okMsg) toast(okMsg); } catch (e) { toast(e.message, "err"); }
  };
  const remove = (doc) => {
    if (!window.confirm(`Supprimer « ${doc.filename} » de la base de connaissances ? Ses passages ne seront plus utilisés par l'assistante.`)) return;
    setData((d) => ({ ...d, documents: d.documents.map((x) => (x.id === doc.id ? { ...x, removing: true } : x)) }));
    act(() => api(`/rag/documents/${doc.id}`, { method: "DELETE" }), "Document supprimé.");
  };

  return (
    <div className="stack">
      <div className="split">
        <EngineCard status={status.data} />
        <Uploader maxMb={data.max_mb} />
      </div>
      <section className="card">
        <h3>Documents ({data.documents.length})</h3>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Document</th><th>État</th><th>Pages</th><th>Passages</th><th>Indexé le</th><th /></tr></thead>
            <tbody>
              {data.documents.map((d) => (
                <tr key={d.id} className={d.removing ? "muted" : ""}>
                  <td>
                    <strong>{d.title && d.title !== d.filename ? d.title : d.filename}</strong>
                    <div className="tiny muted">{d.filename} · {d.origin === "builtin" ? "corpus intégré" : "déposé"} · {Math.round((d.size_bytes || 0) / 1024)} Ko</div>
                  </td>
                  <td><StatusPill doc={d} /></td>
                  <td className="small">
                    {d.pages ?? "—"}
                    {d.ocr_pages > 0 && <div className="tiny">{d.ocr_pages} par OCR</div>}
                    {d.empty_pages > 0 && <div className="tiny form-error">{d.empty_pages} vide(s)</div>}
                  </td>
                  <td className="small">{d.status === "ready" ? d.chunks : "—"}</td>
                  <td className="tiny">{d.indexed_at ? fmtDate(d.indexed_at, true) : "—"}</td>
                  <td><div className="row-actions">
                    {d.status === "ready" && <button className="link small" onClick={() => setDetail(d.id)}>Passages</button>}
                    <button className="link small" disabled={BUSY.has(d.status) || d.removing}
                      onClick={() => act(() => api(`/rag/documents/${d.id}/reindex`, { method: "POST" }), "Réindexation lancée.")}>Réindexer</button>
                    <button className="link small danger" disabled={d.removing} onClick={() => remove(d)}>Supprimer</button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {detail && <DocumentDetail id={detail} onClose={() => setDetail(null)} />}
      <SearchTester />
    </div>
  );
}
