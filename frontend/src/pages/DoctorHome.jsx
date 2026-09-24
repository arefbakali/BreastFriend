import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Calendar from "../components/Calendar.jsx";
import Icon from "../components/icons.jsx";
import PatientCard from "../components/PatientCard.jsx";
import { ErrorBox, Spinner, useFetch } from "../components/ui.jsx";
import { navigate } from "../router.js";
import { fmtDate } from "../utils.js";

export function NotesBox({ patientId = null, rows = 8 }) {
  const [body, setBody] = useState("");
  const [saved, setSaved] = useState(null);
  const loaded = useRef(false);
  const timer = useRef(null);
  useEffect(() => {
    loaded.current = false;
    api(`/doctor/notes${patientId ? `?patient_id=${patientId}` : ""}`).then((d) => {
      setBody(d.note.body || "");
      setSaved(d.note.updated_at);
      loaded.current = true;
    });
  }, [patientId]);
  const change = (v) => {
    setBody(v);
    setSaved("…");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api("/doctor/notes", { method: "PUT", body: { body: v, patient_id: patientId } }).then((d) => setSaved(d.note.updated_at));
    }, 700);
  };
  return (
    <div className="notes">
      <textarea rows={rows} value={body} onChange={(e) => change(e.target.value)} placeholder="Écrivez vos notes ici…" aria-label="Notes" />
      <span className="tiny muted">{saved === "…" ? "Enregistrement…" : saved ? `Enregistré (${saved})` : "Enregistrement automatique"}</span>
    </div>
  );
}

export default function DoctorHome() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const dash = useFetch("/doctor/dashboard");
  const pts = useFetch(`/doctor/patients?q=${encodeURIComponent(search)}`);
  const cal = useFetch("/doctor/appointments");
  const notifs = useFetch("/notifications");

  useEffect(() => { const t = setTimeout(() => setSearch(q), 250); return () => clearTimeout(t); }, [q]);

  if (dash.loading && !dash.data) return <Spinner />;
  if (dash.error && !dash.data) return <ErrorBox message={dash.error} onRetry={dash.reload} />;
  const s = dash.data.stats;
  const pending = (notifs.data?.notifications || []).filter((n) => !n.is_read).slice(0, 4);

  return (
    <div className="doctor-home">
      <form className="searchbar" onSubmit={(e) => { e.preventDefault(); setSearch(q); }}>
        <Icon name="search" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher une patiente…" aria-label="Rechercher une patiente" />
        <button className="btn primary">Rechercher</button>
      </form>
      <div className="stats">
        <div><strong>{s.patients}</strong><span>patientes suivies</span></div>
        <div className={s.urgent_reports ? "alert" : ""}><strong>{s.urgent_reports}</strong><span>comptes rendus prioritaires</span></div>
        <div><strong>{s.pending_reports}</strong><span>comptes rendus à lire</span></div>
        <div><strong>{s.appointments_today}</strong><span>rendez-vous aujourd'hui</span></div>
      </div>
      <div className="doctor-layout">
        <section>
          {pts.loading && !pts.data ? <Spinner /> : (
            <div className="patient-grid">
              {pts.data?.patients.map((p) => <PatientCard key={p.id} p={p} />)}
              {pts.data?.patients.length === 0 && <p className="muted">Aucune patiente ne correspond à « {search} ».</p>}
            </div>
          )}
        </section>
        <aside className="stack">
          <section className="card">
            <h3>Agenda</h3>
            <Calendar compact events={cal.data?.appointments || []} onSelect={() => navigate("/doctor/calendar")}
              onDayClick={() => navigate("/doctor/calendar")} />
          </section>
          <section className="card">
            <h3>À traiter</h3>
            {pending.length === 0 && <p className="muted small">Tout est à jour.</p>}
            <ul className="plain notif-mini">
              {pending.map((n) => (
                <li key={n.id} className={`k-${n.kind}`}>
                  <a href={`#${n.link || "/doctor/notifications"}`}>{n.title}</a>
                  {n.body && <span className="small muted"> — {n.body}</span>}
                  <span className="tiny muted block">{fmtDate(n.created_at, true)}</span>
                </li>
              ))}
            </ul>
            <a className="link small" href="#/doctor/notifications">Toutes les notifications</a>
          </section>
          <section className="card">
            <h3>Notes</h3>
            <NotesBox />
          </section>
        </aside>
      </div>
    </div>
  );
}
