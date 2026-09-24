import React, { useState } from "react";
import AppointmentModal from "../components/AppointmentModal.jsx";
import Calendar from "../components/Calendar.jsx";
import { ErrorBox, Spinner, useFetch } from "../components/ui.jsx";

export default function CalendarPage() {
  const cal = useFetch("/doctor/appointments");
  const pts = useFetch("/doctor/patients");
  const [modal, setModal] = useState(null);
  if (cal.loading && !cal.data) return <Spinner />;
  if (cal.error && !cal.data) return <ErrorBox message={cal.error} onRetry={cal.reload} />;
  return (
    <div>
      <div className="toolbar">
        <p className="muted small">Cliquez sur un jour pour créer un rendez-vous, ou sur un rendez-vous pour le modifier.</p>
        <button className="btn primary" onClick={() => setModal({})}>Nouveau rendez-vous</button>
      </div>
      <section className="card">
        <Calendar events={cal.data.appointments.filter((a) => a.status !== "annule")} onSelect={(a) => setModal(a)} onDayClick={(d) => setModal({ date: d })} />
      </section>
      <div className="legend small">
        <span className="k-consultation">Consultation</span><span className="k-check-in">Check-in</span>
        <span className="k-mammographie">Mammographie</span><span className="k-chimiotherapie">Chimiothérapie</span>
      </div>
      {modal && (
        <AppointmentModal appointment={modal.id ? modal : null} defaultDate={modal.date} patients={pts.data?.patients || []}
          onClose={() => setModal(null)} onSaved={() => { setModal(null); cal.reload(); }} />
      )}
    </div>
  );
}
