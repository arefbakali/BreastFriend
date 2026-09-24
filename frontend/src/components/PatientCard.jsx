import React from "react";
import { Avatar, TriageBadge } from "./ui.jsx";
import { STATUS, fmtDate, relDays } from "../utils.js";

export default function PatientCard({ p }) {
  const r = p.last_report;
  return (
    <article className={`patient-card ${r && !r.reviewed ? `t-${r.triage}` : ""}`}>
      <Avatar src={p.avatar} name={p.full_name} size={96} />
      <div className="pc-body">
        <h3>{p.full_name}</h3>
        <p className="small muted">{STATUS[p.status] || p.status}</p>
        <p className="small"><strong>Prochain RDV :</strong> {p.next_appointment ? `${fmtDate(p.next_appointment.starts_at)} (${relDays(p.next_appointment.starts_at)})` : "—"}</p>
        <TriageBadge level={r?.triage} reviewed={r?.reviewed} />
        {p.unread_messages > 0 && <span className="badge info">{p.unread_messages} message{p.unread_messages > 1 ? "s" : ""}</span>}
      </div>
      <a className="btn primary small" href={`#/doctor/patients/${p.id}`}>Voir</a>
    </article>
  );
}
