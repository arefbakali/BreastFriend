import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import AppointmentModal from "../components/AppointmentModal.jsx";
import MessageThread from "../components/MessageThread.jsx";
import { Avatar, ErrorBox, Spinner, Tabs, TriageBadge, toast, useFetch } from "../components/ui.jsx";
import { KINDS, STATUS, TRIAGE, fmtDate, relDays } from "../utils.js";
import { NotesBox } from "./DoctorHome.jsx";

function QuestionsEditor({ pid, questionSet, onChange }) {
  const [items, setItems] = useState(questionSet?.questions || []);
  const [cats, setCats] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => setItems(questionSet?.questions || []), [questionSet]);
  useEffect(() => { api("/doctor/categories").then((d) => setCats(d.categories)); }, []);

  const regen = async () => {
    setBusy(true);
    try {
      const d = await api(`/doctor/patients/${pid}/questions/generate`, { method: "POST" });
      setItems(d.question_set.questions);
      onChange();
      toast("Nouvelles questions générées à partir du corpus.");
    } catch (e) { toast(e.message, "err"); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      await api(`/doctor/patients/${pid}/questions`, { method: "PUT", body: { questions: items, confirm: true, source: questionSet?.source } });
      onChange();
      toast("Questions confirmées : la patiente les recevra pour son check-in.");
    } catch (e) { toast(e.message, "err"); } finally { setBusy(false); }
  };
  const upd = (i, k, v) => setItems(items.map((q, j) => (j === i ? { ...q, [k]: v } : q)));
  const move = (i, d) => {
    const n = [...items];
    const [x] = n.splice(i, 1);
    n.splice(i + d, 0, x);
    setItems(n);
  };

  return (
    <div>
      <div className="q-editor-head">
        <p className="small">
          {questionSet ? (
            <>Source : <strong>{{ bank: "banque validée", rag: "RAG (banque + passages du corpus)", "rag+llm": "RAG + LLM", doctor: "médecin" }[questionSet.source] || questionSet.source}</strong>
              {" · "}{questionSet.confirmed ? `confirmées le ${questionSet.confirmed_at}` : "non confirmées"}</>
          ) : "Aucun questionnaire préparé pour le prochain check-in."}
        </p>
        <button className="btn ghost small" onClick={regen} disabled={busy}>Régénérer avec le RAG</button>
      </div>
      <ol className="q-editor">
        {items.map((q, i) => (
          <li key={i}>
            <div className="q-row">
              <select value={q.category} onChange={(e) => upd(i, "category", e.target.value)} aria-label="Catégorie">
                {Object.entries(cats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <input value={q.text} onChange={(e) => upd(i, "text", e.target.value)} aria-label={`Question ${i + 1}`} />
              <div className="q-actions">
                <button className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Monter">↑</button>
                <button className="icon-btn" disabled={i === items.length - 1} onClick={() => move(i, 1)} aria-label="Descendre">↓</button>
                <button className="icon-btn" onClick={() => setItems(items.filter((_, j) => j !== i))} aria-label="Supprimer">×</button>
              </div>
            </div>
            {q.rationale && <p className="rationale tiny">Ancrée dans : {q.rationale.title} — {q.rationale.section}. <em>{q.rationale.excerpt}</em></p>}
          </li>
        ))}
      </ol>
      <div className="actions">
        <button className="btn ghost" onClick={() => setItems([...items, { category: "size_shape", text: "" }])}>Ajouter une question</button>
        <button className="btn primary" onClick={save} disabled={busy || items.length < 3}>Confirmer ces questions</button>
      </div>
    </div>
  );
}

function RiskHistory({ history }) {
  if (!history.length) return <p className="muted small">Pas encore de compte rendu.</p>;
  const max = Math.max(8, ...history.map((h) => h.risk_score));
  return (
    <div className="risk-chart" role="img" aria-label="Évolution du score de vigilance">
      {history.map((h, i) => (
        <div key={i} className="risk-col" title={`${h.date} : score ${h.risk_score} (${TRIAGE[h.triage].label})`}>
          <span className={`bar ${TRIAGE[h.triage].cls}`} style={{ height: `${Math.max(6, (h.risk_score / max) * 100)}%` }} />
          <span className="tiny">{h.date.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}

export default function PatientDetail({ params, query }) {
  const pid = params.id;
  const [tab, setTab] = useState(query.tab || "overview");
  const [modal, setModal] = useState(null);
  const { data, error, loading, reload } = useFetch(`/doctor/patients/${pid}`);
  useEffect(() => { if (query.tab) setTab(query.tab); }, [query.tab]);
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const p = data.patient;

  const updateProfile = async (body) => {
    await api(`/doctor/patients/${pid}`, { method: "PUT", body });
    toast("Dossier mis à jour.");
    reload();
  };

  return (
    <div>
      <a className="back" href="#/doctor/patients">‹ Toutes les patientes</a>
      <header className="patient-head card">
        <Avatar src={p.avatar} name={p.full_name} size={84} />
        <div>
          <h2>{p.full_name}</h2>
          <p className="muted small">Née le {p.birth_date ? fmtDate(p.birth_date) : "—"} · {p.email || "pas d'e-mail"} · {p.phone || ""}</p>
          <p className="small">{STATUS[p.status]}{p.treatment ? ` — ${p.treatment}` : ""}{p.family_history ? " · antécédents familiaux" : ""}</p>
        </div>
        <div className="patient-head-right">
          <TriageBadge level={p.last_report?.triage} reviewed={p.last_report?.reviewed} />
          <button className="btn primary small" onClick={() => setModal({})}>Nouveau rendez-vous</button>
        </div>
      </header>
      <Tabs value={tab} onChange={setTab} tabs={[
        ["overview", "Aperçu"], ["reports", "Comptes rendus", data.reports.filter((r) => !r.reviewed).length],
        ["questions", "Questions du check-in"], ["appointments", "Rendez-vous"], ["messages", "Messages", p.unread_messages],
      ]} />

      {tab === "overview" && (
        <div className="split">
          <section className="card">
            <h3>Évolution du score de vigilance</h3>
            <RiskHistory history={data.risk_history} />
            <h3>Situation</h3>
            <div className="row2">
              <label>Statut
                <select value={p.status} onChange={(e) => updateProfile({ status: e.target.value })}>
                  {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>Traitement
                <input defaultValue={p.treatment || ""} onBlur={(e) => e.target.value !== (p.treatment || "") && updateProfile({ treatment: e.target.value })} />
              </label>
            </div>
            <p className="small muted">Dernière autopalpation : {p.last_self_exam ? fmtDate(p.last_self_exam) : "jamais"}.
              Prochain RDV : {p.next_appointment ? `${fmtDate(p.next_appointment.starts_at, true)} (${relDays(p.next_appointment.starts_at)})` : "aucun"}.</p>
          </section>
          <section className="card">
            <h3>Notes privées sur la patiente</h3>
            <NotesBox patientId={Number(pid)} rows={10} />
          </section>
        </div>
      )}

      {tab === "reports" && (
        <div className="list">
          {data.reports.length === 0 && <p className="muted">Aucun compte rendu.</p>}
          {data.reports.map((r) => (
            <a key={r.id} className="row-item" href={`#/doctor/reports/${r.id}`}>
              <div><strong>{fmtDate(r.created_at, true)}</strong><p className="small muted">Score {r.risk_score}{r.doctor_comment ? ` · « ${r.doctor_comment} »` : ""}</p></div>
              <TriageBadge level={r.triage} reviewed={r.reviewed} />
            </a>
          ))}
        </div>
      )}

      {tab === "questions" && <section className="card"><QuestionsEditor pid={pid} questionSet={data.question_set} onChange={reload} /></section>}

      {tab === "appointments" && (
        <section className="card">
          <ul className="plain appt-list">
            {data.appointments.map((a) => (
              <li key={a.id} className={`appt-row ${a.status}`}>
                <button className="link" onClick={() => setModal(a)}>{fmtDate(a.starts_at, true)}</button>
                <span>{KINDS[a.kind] || a.kind}</span>
                <span className="small muted">{a.status === "annule" ? "annulé" : a.status === "fait" ? "fait" : relDays(a.starts_at)}</span>
                {a.notes && <span className="small">{a.notes}</span>}
              </li>
            ))}
          </ul>
          {data.appointments.length === 0 && <p className="muted small">Aucun rendez-vous.</p>}
        </section>
      )}

      {tab === "messages" && <section className="card"><MessageThread path={`/doctor/patients/${pid}/messages`} /></section>}

      {modal && <AppointmentModal appointment={modal.id ? { ...modal, patient_name: p.full_name } : null} patientId={Number(pid)}
        onClose={() => setModal(null)} onSaved={() => { setModal(null); reload(); }} />}
    </div>
  );
}
