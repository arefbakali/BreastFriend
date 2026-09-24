import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Icon from "./icons.jsx";
import { useAuth } from "../auth.jsx";
import { fmtDate } from "../utils.js";
import { ErrorBox, Spinner, useFetch } from "./ui.jsx";

// Messagerie : la liste est une donnée partagée, rafraîchie par les événements temps réel
// (« message ») — plus de sondage toutes les 15 s. L'envoi est affiché immédiatement.
export default function MessageThread({ path }) {
  const { user } = useAuth();
  const q = useFetch(path);
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(null);
  const end = useRef(null);
  const messages = q.data?.messages;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [messages?.length]);

  const send = async (e) => {
    e?.preventDefault();
    const text = (failed ?? body).trim();
    if (!text || sending) return;
    const temp = { id: `tmp-${Date.now()}`, body: text, sender_id: user.id, sender_name: user.full_name,
                   created_at: new Date().toISOString(), pending: true };
    q.setData((d) => ({ ...(d || {}), messages: [...(d?.messages || []), temp] }));   // affichage immédiat
    setBody("");
    setFailed(null);
    setSending(true);
    try {
      const d = await api(path, { method: "POST", body: { body: text } });
      q.setData(d);
    } catch (err) {
      q.setData((d) => d && { ...d, messages: d.messages.filter((m) => m.id !== temp.id) });
      setFailed(text);
      setBody(text);
      console.warn("Message non envoyé", err);
    } finally {
      setSending(false);
    }
  };

  if (q.error && !messages) return <ErrorBox message={q.error} onRetry={q.reload} />;
  if (!messages) return <Spinner label="Chargement des messages…" />;
  return (
    <div className="messages">
      <div className="messages-list" aria-live="polite">
        {messages.length === 0 && <p className="muted small center">Aucun message. Écrivez le premier.</p>}
        {messages.map((m) => (
          <div key={m.id} className={`pm ${m.sender_id === user.id ? "mine" : ""} ${m.pending ? "pending" : ""}`}>
            <p>{m.body}</p>
            <span className="tiny">{m.sender_name} · {m.pending ? "envoi…" : fmtDate(m.created_at, true)}</span>
          </div>
        ))}
        <div ref={end} />
      </div>
      {failed && (
        <p className="form-error small" role="alert">
          Le message n'a pas pu être envoyé. <button className="link" onClick={send}>Réessayer</button>
        </p>
      )}
      <form className="messages-form" onSubmit={send}>
        <input value={body} onChange={(e) => { setBody(e.target.value); setFailed(null); }} placeholder="Votre message…" aria-label="Message" />
        <button className="btn primary" disabled={sending || !body.trim()}><Icon name="send" size={16} /> Envoyer</button>
      </form>
    </div>
  );
}
