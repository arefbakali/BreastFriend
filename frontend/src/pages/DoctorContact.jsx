import React from "react";
import MessageThread from "../components/MessageThread.jsx";
import { Avatar, ErrorBox, Spinner, useFetch } from "../components/ui.jsx";
import { KINDS, fmtDate, relDays } from "../utils.js";

export default function DoctorContact() {
  const dash = useFetch("/patient/dashboard");
  const appts = useFetch("/patient/appointments");
  if ((dash.loading && !dash.data) || (appts.loading && !appts.data)) return <Spinner />;
  if (dash.error && !dash.data) return <ErrorBox message={dash.error} onRetry={dash.reload} />;
  const doc = dash.data.doctor;
  const now = new Date().toISOString().slice(0, 16);
  const upcoming = (appts.data?.appointments || []).filter((a) => a.starts_at >= now && a.status === "prevu").reverse();
  const past = (appts.data?.appointments || []).filter((a) => a.starts_at < now || a.status !== "prevu");
  return (
    <div className="split wide-left">
      <section className="card">
        <h2>Messages</h2>
        {doc ? <MessageThread path="/patient/messages" /> : <p>Aucun médecin n'est associé à votre compte.</p>}
      </section>
      <div className="stack">
        {doc && (
          <section className="card doctor-card">
            <Avatar src={doc.avatar} name={doc.full_name} size={64} />
            <div>
              <h3>{doc.full_name}</h3>
              <p className="muted">{doc.specialty}</p>
              {doc.phone && <p className="small">{doc.phone}</p>}
              {doc.email && <p className="small">{doc.email}</p>}
            </div>
          </section>
        )}
        <section className="card">
          <h3>Mes rendez-vous</h3>
          {upcoming.length === 0 && <p className="muted small">Aucun rendez-vous à venir.</p>}
          <ul className="plain appt-list">
            {upcoming.map((a) => (
              <li key={a.id}><strong>{KINDS[a.kind] || a.kind}</strong> — {fmtDate(a.starts_at, true)} <span className="muted">({relDays(a.starts_at)})</span>
                {a.notes && <p className="small muted">{a.notes}</p>}</li>
            ))}
          </ul>
          {past.length > 0 && (
            <details><summary className="small">Historique ({past.length})</summary>
              <ul className="plain appt-list">{past.map((a) => <li key={a.id} className="muted small">{KINDS[a.kind] || a.kind} — {fmtDate(a.starts_at)} · {a.status === "annule" ? "annulé" : "passé"}</li>)}</ul>
            </details>
          )}
        </section>
        <section className="card soft">
          <h3>En cas d'urgence</h3>
          <p className="small">Fièvre de 38 °C ou plus pendant une chimiothérapie, difficulté à respirer, saignement important : appelez le <strong>SAMU 190</strong> sans attendre la réponse de votre médecin.</p>
        </section>
      </div>
    </div>
  );
}
