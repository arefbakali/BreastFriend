import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Icon from "../components/icons.jsx";
import { Avatar, ErrorBox, Spinner, TriageBadge, useFetch } from "../components/ui.jsx";
import { useAuth } from "../auth.jsx";

export default function Questionnaire() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useFetch("/patient/questionnaire");
  const [answers, setAnswers] = useState({});
  const [current, setCurrent] = useState(0);
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const end = useRef(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [current, result]);

  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const qs = data.questions;
  const finished = current >= qs.length;

  const answer = (value, text) => {
    const q = qs[current];
    setAnswers({ ...answers, [q.id]: { value, text: text || { yes: "Oui", no: "Non", unknown: "Je ne sais pas" }[value] } });
    setDraft("");
    setCurrent(current + 1);
  };
  const typed = (e) => {
    e.preventDefault();
    if (draft.trim()) answer(null, draft.trim());
  };
  const edit = (i) => { if (!result) setCurrent(i); };
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const payload = Object.fromEntries(Object.entries(answers).map(([k, a]) => [k, a.value ? { value: a.value, text: a.text } : { text: a.text }]));
      setResult(await api("/patient/questionnaire", { method: "POST", body: { question_set_id: data.question_set_id, answers: payload } }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const restart = () => { setAnswers({}); setCurrent(0); setResult(null); reload(); };

  return (
    <div className="questionnaire">
      <div className="q-intro">
        <p>Répondez après votre autopalpation. Vos réponses deviennent un compte rendu transmis à votre médecin.</p>
        <span className={`badge ${data.confirmed ? "ok" : "muted"}`}>{data.confirmed ? "Questions validées par votre médecin" : "Questions générées depuis le corpus médical"}</span>
      </div>
      <div className="progress" aria-label={`${Math.min(current, qs.length)} sur ${qs.length}`}>
        <span style={{ width: `${(Math.min(current, qs.length) / qs.length) * 100}%` }} />
      </div>
      <div className="thread">
        {qs.slice(0, Math.min(current + 1, qs.length)).map((q, i) => (
          <React.Fragment key={q.id}>
            <div className="bubble bot">
              <img src="/doctor-avatar.svg" alt="" className="bubble-avatar" />
              <p>{q.text}</p>
            </div>
            {answers[q.id] && i < current && (
              <div className="bubble me" onClick={() => edit(i)} title={result ? "" : "Cliquer pour modifier"}>
                <p>{answers[q.id].text}</p>
                <Avatar src={user.avatar} name={user.full_name} size={38} />
              </div>
            )}
          </React.Fragment>
        ))}
        {finished && !result && (
          <div className="bubble bot">
            <img src="/doctor-avatar.svg" alt="" className="bubble-avatar" />
            <p>Merci pour vos réponses. Vous pouvez cliquer sur une réponse pour la modifier, puis envoyer le questionnaire.</p>
          </div>
        )}
        {result && (
          <div className={`result-card t-${result.triage.level}`}>
            <TriageBadge level={result.triage.level} />
            <p>{result.message}</p>
            <div className="actions">
              <a className="btn primary" href={`#/reports/${result.report_id}`}>Voir mon compte rendu</a>
              <a className="btn ghost" href="#/doctor-contact">Écrire à mon médecin</a>
              <button className="btn ghost" onClick={restart}>Nouveau questionnaire</button>
            </div>
          </div>
        )}
        <div ref={end} />
      </div>
      <ErrorBox>{err}</ErrorBox>
      {!finished && (
        <div className="answer-bar">
          <div className="quick">
            <button className="btn yes" onClick={() => answer("yes")}>Oui</button>
            <button className="btn no" onClick={() => answer("no")}>Non</button>
            <button className="btn ghost" onClick={() => answer("unknown")}>Je ne sais pas</button>
          </div>
          <form onSubmit={typed} className="typed">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ou répondez avec vos mots (ex : « Oui, une petite boule à gauche »)" aria-label="Réponse libre" />
            <button className="icon-btn send" aria-label="Envoyer la réponse"><Icon name="send" /></button>
          </form>
        </div>
      )}
      {finished && !result && (
        <div className="answer-bar end">
          <button className="btn primary" onClick={submit} disabled={busy}><Icon name="send" size={18} /> {busy ? "Envoi…" : "Envoyer à mon médecin"}</button>
        </div>
      )}
    </div>
  );
}
