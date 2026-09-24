import React, { useState } from "react";
import { useAuth } from "../auth.jsx";
import { ErrorBox } from "../components/ui.jsx";

const DEMO = [
  ["dr.amel", "Dr Amel Ben Salah", "Oncologue"],
  ["leila", "Leïla", "Patiente en rémission"],
  ["meriem", "Meriem", "Patiente sous chimio"],
  ["salma", "Salma", "Patiente en prévention"],
];

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e, u = username, p = password) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(u, p);
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
          <p className="tagline">Parce qu'on a toutes besoin d'une BreastFriend.</p>
        </section>
        <section className="auth-form">
          <h2>Bienvenue</h2>
          <form onSubmit={submit}>
            <label>Identifiant
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </label>
            <label>Mot de passe
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            <ErrorBox>{error}</ErrorBox>
            <button className="btn primary wide" disabled={busy}>{busy ? "Connexion…" : "Se connecter"}</button>
          </form>
          <p className="small center">Pas encore de compte ? <a href="#/register">Créer un compte</a></p>
          <div className="demo">
            <p className="small muted">Comptes de démonstration (mot de passe : demo1234)</p>
            <div className="demo-list">
              {DEMO.map(([u, name, role]) => (
                <button key={u} type="button" className="demo-btn" onClick={() => submit(null, u, "demo1234")} disabled={busy}>
                  <strong>{name}</strong><span>{role}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
