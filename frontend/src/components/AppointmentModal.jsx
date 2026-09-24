import React, { useState } from "react";
import { api } from "../api.js";
import { KINDS } from "../utils.js";
import { ErrorBox, Modal, toast } from "./ui.jsx";

export default function AppointmentModal({ appointment, patients = [], patientId, defaultDate, onClose, onSaved }) {
  const editing = Boolean(appointment?.id);
  const [f, setF] = useState({
    patient_id: appointment?.patient_id || patientId || patients[0]?.id || "",
    date: appointment?.starts_at?.slice(0, 10) || defaultDate || new Date().toISOString().slice(0, 10),
    time: appointment?.starts_at?.slice(11, 16) || "10:00",
    kind: appointment?.kind || "consultation",
    notes: appointment?.notes || "",
  });
  const [error, setError] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    const body = { patient_id: Number(f.patient_id), starts_at: `${f.date}T${f.time}`, kind: f.kind, notes: f.notes };
    try {
      if (editing) await api(`/doctor/appointments/${appointment.id}`, { method: "PATCH", body });
      else await api("/doctor/appointments", { method: "POST", body });
      toast(editing ? "Rendez-vous modifié." : "Rendez-vous créé, la patiente est prévenue.");
      onSaved();
    } catch (err) { setError(err.message); }
  };
  const setStatus = async (status) => {
    await api(`/doctor/appointments/${appointment.id}`, { method: "PATCH", body: { status } });
    toast(status === "annule" ? "Rendez-vous annulé." : "Rendez-vous marqué comme fait.");
    onSaved();
  };

  return (
    <Modal title={editing ? `Rendez-vous — ${appointment.patient_name || ""}` : "Nouveau rendez-vous"} onClose={onClose}>
      <form onSubmit={save} className="form">
        {!patientId && !editing && (
          <label>Patiente
            <select value={f.patient_id} onChange={set("patient_id")} required>
              {patients.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
            </select>
          </label>
        )}
        <div className="row2">
          <label>Date<input type="date" value={f.date} onChange={set("date")} required /></label>
          <label>Heure<input type="time" value={f.time} onChange={set("time")} required /></label>
        </div>
        <label>Type
          <select value={f.kind} onChange={set("kind")}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        <label>Notes<textarea rows={3} value={f.notes} onChange={set("notes")} /></label>
        <ErrorBox>{error}</ErrorBox>
        <div className="actions">
          <button className="btn primary">{editing ? "Enregistrer" : "Créer le rendez-vous"}</button>
          {editing && appointment.status === "prevu" && (
            <>
              <button type="button" className="btn ghost" onClick={() => setStatus("fait")}>Marquer comme fait</button>
              <button type="button" className="btn danger" onClick={() => setStatus("annule")}>Annuler le RDV</button>
            </>
          )}
        </div>
      </form>
    </Modal>
  );
}
