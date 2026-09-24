import React from "react";
import ReportView from "../components/ReportView.jsx";
import { Empty, ErrorBox, Spinner, TriageBadge, useFetch } from "../components/ui.jsx";
import { fmtDate } from "../utils.js";

export function PatientReports() {
  const { data, error, loading, reload } = useFetch("/patient/reports");
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  if (!data.reports.length)
    return <Empty title="Aucun compte rendu pour l'instant" action={<a className="btn primary" href="#/questionnaire">Répondre au questionnaire</a>}>
      Après votre autopalpation, répondez au questionnaire : un compte rendu sera créé et envoyé à votre médecin.</Empty>;
  return (
    <div className="list">
      {data.reports.map((r) => (
        <a key={r.id} className="row-item" href={`#/reports/${r.id}`}>
          <div>
            <strong>Compte rendu du {fmtDate(r.created_at)}</strong>
            <p className="small muted">{r.reviewed ? "Lu par votre médecin" : "En attente de lecture"}{r.doctor_comment ? ` · « ${r.doctor_comment} »` : ""}</p>
          </div>
          <TriageBadge level={r.triage} />
        </a>
      ))}
    </div>
  );
}

export function PatientReport({ params }) {
  const { data, error, loading, reload } = useFetch(`/patient/reports/${params.id}`);
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  return (
    <>
      <a className="back" href="#/reports">‹ Tous mes comptes rendus</a>
      <ReportView report={data.report} />
    </>
  );
}
