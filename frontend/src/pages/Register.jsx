import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { ErrorBox } from "../components/ui.jsx";

export default function Register() {
  const { register } = useAuth();
  const [doctors, setDoctors] = useState([]);
  const [f, setF] = useState({ role: "patient", full_name: "", username: "", password: "", email: "", status: "prevention",
    doctor_id: "", family_history: false, specialty: "", invite_code: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/auth/doctors").then((d) => setDoctors(d.doctors)).catch(() => {}); }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register({ ...f, doctor_id: f.doctor_id ? Number(f.doctor_id) : null });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <section className="auth-brand">
          <img src="/logo.png" alt="" />
          <h1 className="sr-only">BreastFriend</h1>
          <p className="tagline">Prévention, soutien et suivi, au même endroit.</p>
        </section>
        <section className="auth-form">
          <h2>Créer un compte</h2>
          <div className="seg wide" role="group">
            <button type="button" className={f.role === "patient" ? "on" : ""} onClick={() => setF({ ...f, role: "patient" })}>Je suis une patiente</button>
            <button type="button" className={f.role === "doctor" ? "on" : ""} onClick={() => setF({ ...f, role: "doctor" })}>Je suis médecin</button>
          </div>
          <form onSubmit={submit}>
            <label>Nom complet<input value={f.full_name} onChange={set("full_name")} required /></label>
            <div className="row2">
              <label>Identifiant<input value={f.username} onChange={set("username")} minLength={3} required /></label>
              <label>Mot de passe<input type="password" value={f.password} onChange={set("password")} minLength={6} required /></label>
            </div>
            <label>E-mail (facultatif)<input type="email" value={f.email} onChange={set("email")} /></label>
            {f.role === "patient" ? (
              <>
                <div className="row2">
                  <label>Mon médecin
                    <select value={f.doctor_id} onChange={set("doctor_id")}>
                      <option value="">Choisir…</option>
                      {doctors.map((d) => <option key={d.id} value={d.id}>{d.full_name} — {d.specialty}</option>)}
                    </select>
                  </label>
                  <label>Ma situation
                    <select value={f.status} onChange={set("status")}>
                      <option value="prevention">Prévention / dépistage</option>
                      <option value="traitement">En traitement</option>
                      <option value="remission">Après traitement</option>
                    </select>
                  </label>
                </div>
                <label className="check"><input type="checkbox" checked={f.family_history} onChange={set("family_history")} />
                  Antécédents de cancer du sein dans ma famille</label>
              </>
            ) : (
              <div className="row2">
                <label>Spécialité<input value={f.specialty} onChange={set("specialty")} placeholder="Oncologue, gynécologue…" /></label>
                <label>Code d'invitation<input value={f.invite_code} onChange={set("invite_code")} required placeholder="BF-MEDECIN-2024" /></label>
              </div>
            )}
            <ErrorBox>{error}</ErrorBox>
            <button className="btn primary wide" disabled={busy}>{busy ? "Création…" : "Créer mon compte"}</button>
          </form>
          <p className="small center">Déjà inscrite ? <a href="#/login">Se connecter</a></p>
        </section>
      </div>
    </div>
  );
}
