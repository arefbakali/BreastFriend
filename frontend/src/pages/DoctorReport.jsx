import React, { useState } from "react";
import { api } from "../api.js";
import ReportView from "../components/ReportView.jsx";
import { ErrorBox, Spinner, toast, useFetch } from "../components/ui.jsx";

export default function DoctorReport({ params }) {
  const { data, error, loading, reload } = useFetch(`/doctor/reports/${params.id}`);
  const [comment, setComment] = useState(null);
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const r = data.report;
  const value = comment ?? r.doctor_comment ?? "";
  const review = async () => {
    await api(`/doctor/reports/${r.id}`, { method: "PATCH", body: { reviewed: true, doctor_comment: value } });
    toast("Compte rendu marqué comme lu. La patiente est prévenue.");
    reload();
  };
  return (
    <div>
      <a className="back" href={`#/doctor/patients/${r.patient_id}?tab=reports`}>‹ Dossier de {r.patient_name}</a>
      <div className="split wide-left">
        <ReportView report={r} questions={r.questions} forDoctor />
        <aside className="stack">
          <section className="card">
            <h3>{r.reviewed ? "Compte rendu lu" : "Lecture du compte rendu"}</h3>
            <label>Message pour la patiente (facultatif)
              <textarea rows={5} value={value} onChange={(e) => setComment(e.target.value)}
                placeholder="Ex : Merci, je vous propose un rendez-vous la semaine prochaine." />
            </label>
            <button className="btn primary wide" onClick={review}>{r.reviewed ? "Mettre à jour le commentaire" : "Marquer comme lu et répondre"}</button>
          </section>
          <section className="card">
            <h3>Suite</h3>
            <a className="btn ghost wide" href={`#/doctor/patients/${r.patient_id}?tab=appointments`}>Planifier un rendez-vous</a>
            <a className="btn ghost wide" href={`#/doctor/patients/${r.patient_id}?tab=messages`}>Écrire à la patiente</a>
          </section>
        </aside>
      </div>
    </div>
  );
}
