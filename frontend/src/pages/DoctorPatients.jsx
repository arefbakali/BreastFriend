import React, { useEffect, useState } from "react";
import { Avatar, ErrorBox, Spinner, TriageBadge, useFetch } from "../components/ui.jsx";
import Icon from "../components/icons.jsx";
import { STATUS, fmtDate } from "../utils.js";

export default function DoctorPatients() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useFetch(`/doctor/patients?q=${encodeURIComponent(search)}`);
  useEffect(() => { const t = setTimeout(() => setSearch(q), 250); return () => clearTimeout(t); }, [q]);
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const rows = (data?.patients || []).filter((p) => !status || p.status === status);
  return (
    <div>
      <div className="toolbar">
        <div className="searchbar small-bar">
          <Icon name="search" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom ou identifiant…" aria-label="Rechercher" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrer par situation">
          <option value="">Toutes les situations</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {loading && !data ? <Spinner /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Patiente</th><th>Situation</th><th>Dernier compte rendu</th><th>Prochain RDV</th><th /></tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td><span className="cell-user"><Avatar src={p.avatar} name={p.full_name} size={36} /> {p.full_name}</span></td>
                  <td>{STATUS[p.status]}</td>
                  <td>{p.last_report ? <><TriageBadge level={p.last_report.triage} reviewed={p.last_report.reviewed} /> <span className="small muted">{fmtDate(p.last_report.created_at)}</span></> : "—"}</td>
                  <td>{p.next_appointment ? fmtDate(p.next_appointment.starts_at, true) : "—"}</td>
                  <td><a className="btn ghost small" href={`#/doctor/patients/${p.id}`}>Ouvrir</a></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p className="muted pad">Aucune patiente.</p>}
        </div>
      )}
    </div>
  );
}
