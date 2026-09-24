import React, { useEffect, useRef, useState } from "react";
import { api, streamChat } from "../api.js";
import Icon from "../components/icons.jsx";
import Markdown from "../components/Markdown.jsx";
import { Skeleton, toast, useFetch } from "../components/ui.jsx";

const SUGGESTIONS = [
  "Comment faire mon autopalpation ?",
  "Quels signes doivent m'amener à consulter ?",
  "Que faire si j'ai de la fièvre pendant la chimiothérapie ?",
  "Quelle perruque pour un visage rond ?",
  "Je me sens triste et seule depuis le diagnostic",
  "Que signifie BI-RADS 4 ?",
];

const sourceLabel = (s) => `${s.filename}${s.page ? ` — page ${s.page}` : ""}`;

function Sources({ sources, cited = [], open, onToggle, highlight }) {
  if (!sources?.length) return null;
  // « Sources » = uniquement ce que la réponse cite. Les autres passages consultés restent
  // accessibles, mais ne sont jamais présentés comme appuyant la réponse.
  const citedSources = sources.filter((s) => cited.includes(s.n));
  return (
    <div className="sources">
      {citedSources.length > 0 && (
        <>
          <strong>Sources :</strong>
          <ul>
            {citedSources.map((s) => <li key={s.n}>[{s.n}] {sourceLabel(s)}{s.section ? ` · ${s.section}` : ""}</li>)}
          </ul>
        </>
      )}
      <button className="link small" onClick={onToggle}>
        {open ? "Masquer" : "Voir"} les extraits consultés ({sources.length}){citedSources.length ? "" : " — aucun n'a été retenu pour la réponse"}
      </button>
      {open && (
        <ol>
          {sources.map((s) => (
            <li key={s.n} className={`${highlight === s.n ? "hl" : ""} ${cited.includes(s.n) ? "cited" : ""}`}>
              <span>[{s.n}] {sourceLabel(s)}{cited.includes(s.n) ? " — cité" : ""}</span>
              {s.scores && <span className="scores"> vec {s.scores.vector} · bm25 {s.scores.bm25}{s.scores.rerank !== undefined ? ` · rerank ${s.scores.rerank}` : ""}</span>}
              <p>{s.excerpt}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function Chat({ query }) {
  const history = useFetch("/chat/history");
  const status = useFetch("/rag/status");
  const [messages, setMessages] = useState(null);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState(null);            // null | searching | writing
  const [open, setOpen] = useState({});
  const [hl, setHl] = useState({});
  const end = useRef(null);
  const asked = useRef(false);
  const abort = useRef(null);

  useEffect(() => {
    if (messages === null && history.data) setMessages(history.data.messages);
  }, [history.data, messages]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages, phase]);
  useEffect(() => () => abort.current?.abort(), []);

  const update = (id, patch) => setMessages((l) => l.map((m) => (m.id === id ? { ...m, ...patch } : m)));

  const send = async (msg) => {
    const m = (msg ?? text).trim();
    if (!m || phase) return;
    setText("");
    const aid = `a${Date.now()}`;
    setMessages((l) => [...(l || []).filter((x) => !x.failed), { id: `u${Date.now()}`, role: "user", content: m },
      { id: aid, role: "assistant", content: "", sources: [], streaming: true }]);
    setPhase("searching");
    abort.current = new AbortController();
    try {
      await streamChat(m, (ev) => {
        if (ev.type === "sources") { setPhase("writing"); update(aid, { sources: ev.sources, urgent: ev.urgent }); }
        else if (ev.type === "delta") setMessages((l) => l.map((x) => (x.id === aid ? { ...x, content: x.content + ev.text } : x)));
        else if (ev.type === "done") update(aid, { content: ev.answer, sources: ev.sources, cited: ev.cited, mode: ev.mode, urgent: ev.urgent, streaming: false });
        else if (ev.type === "error") update(aid, { content: ev.error, error: true, failed: m, urgent: ev.urgent, streaming: false });
      }, abort.current.signal);
    } catch (e) {
      if (e.name !== "AbortError") update(aid, { content: e.message, error: true, failed: m, streaming: false });
    } finally {
      setPhase(null);
    }
  };

  useEffect(() => {
    if (messages && query?.q && !asked.current) {
      asked.current = true;
      send(query.q);
      window.history.replaceState(null, "", "#/chat");
    }
  }, [messages, query?.q]); // eslint-disable-line react-hooks/exhaustive-deps -- question transmise une seule fois

  const clear = async () => {
    try {
      await api("/chat/history", { method: "DELETE" });
      setMessages([]);
      toast("Conversation effacée.");
    } catch (e) { toast(e.message, "err"); }
  };

  if (!messages) return <div className="chat"><Skeleton lines={5} height={18} /></div>;
  const llm = status.data?.llm;
  const rag = status.data?.rag;
  return (
    <div className="chat">
      <div className="chat-status">
        {llm && (
          <span className={`badge ${llm.enabled ? "ok" : "muted"}`}>
            {llm.enabled ? `RAG + ${llm.model}` : "Modèle de langage non configuré"}
          </span>
        )}
        {rag && rag.state !== "ready" && <span className="badge muted">{rag.state === "loading" ? "Moteur de recherche en démarrage…" : "Moteur de recherche indisponible"}</span>}
        {rag && <span className="muted small">{rag.ready_documents} documents · {rag.chunks} passages indexés</span>}
        {messages.length > 0 && <button className="link small push" onClick={clear}>Effacer la conversation</button>}
      </div>
      {llm?.data_leaves_device && (
        <p className="remote-note">Vos questions et les extraits de documents sont traités par un service externe ({llm.provider}). N'y écrivez pas d'informations permettant de vous identifier.</p>
      )}
      <div className="chat-thread" aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <img src="/logo.png" alt="" />
            <p>Je suis BreastFriend. Je réponds à vos questions sur le cancer du sein à partir des documents médicaux validés, en citant mes sources.</p>
            <div className="chips">{SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role} ${m.urgent ? "urgent" : ""} ${m.error ? "error" : ""}`}>
            {m.role === "assistant" ? (
              <>
                {m.urgent && m.streaming && <div className="urgent-banner">Signe possible d'urgence : si vous le ressentez maintenant, appelez le SAMU (190) ou votre équipe soignante.</div>}
                {m.streaming && !m.content && <p className="muted small">{phase === "writing" ? "Rédaction de la réponse…" : "Recherche dans les documents…"}</p>}
                {m.content && <Markdown text={m.content} onCite={(n) => { setOpen({ ...open, [m.id]: true }); setHl({ ...hl, [m.id]: n }); }} />}
                {m.error && m.failed && <button className="btn ghost small" onClick={() => send(m.failed)} disabled={!!phase}>Réessayer</button>}
                {!m.streaming && !m.error && (
                  <Sources sources={m.sources} cited={m.cited} open={open[m.id]} highlight={hl[m.id]}
                    onToggle={() => setOpen({ ...open, [m.id]: !open[m.id] })} />
                )}
              </>
            ) : <p>{m.content}</p>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder="Posez votre question…" maxLength={2000}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} aria-label="Votre question" />
        <button className="btn primary" disabled={!!phase || !text.trim()}><Icon name="send" size={18} /> {phase ? "…" : "Envoyer"}</button>
      </form>
      <p className="muted tiny center">Informations générales, pas un diagnostic. En cas d'urgence : SAMU 190.</p>
    </div>
  );
}
