import React from "react";
import Icon from "../components/icons.jsx";
import { ErrorBox, Spinner, TriageBadge, useFetch } from "../components/ui.jsx";
import { KINDS, fmtDate, relDays } from "../utils.js";

export default function PatientHome() {
  const { data, error, loading, reload } = useFetch("/patient/dashboard");
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const { user, self_exam: se, affirmation, next_appointment: appt, last_report: rep, doctor, profile } = data;
  const first = user.full_name.split(" ")[0];

  return (
    <div className="home">
      <p className="greeting">Bonjour {first}, comment allez-vous aujourd'hui ?</p>
      <div className="home-grid">
        <section className={`card check-card ${se.due ? "due" : ""}`}>
          <h2>C'est le moment de vous examiner</h2>
          <img className="check-art" src="/check.svg" alt="" />
          {se.done_this_month ? (
            <p>Autopalpation faite ce mois-ci, bravo. Prochaine le <strong>{fmtDate(se.date)}</strong>.</p>
          ) : se.due ? (
            <p><strong>{se.days_left === 0 ? "C'est aujourd'hui : votre autopalpation mensuelle." : `Votre autopalpation de ce mois est à faire (prévue le ${fmtDate(se.date)}).`}</strong> Cinq minutes suffisent.</p>
          ) : (
            <p>Prochaine autopalpation le <strong>{fmtDate(se.date)}</strong> ({relDays(se.date)}).</p>
          )}
          <div className="actions">
            <a className="btn primary" href="#/self-exam">Suivre le guide</a>
            <a className="btn ghost" href="#/questionnaire">Répondre au questionnaire</a>
          </div>
        </section>

        <section className="card affirmation-card">
          <p className="aff-label"><Icon name="bell" size={18} /> Votre rappel du jour</p>
          <blockquote>{affirmation}</blockquote>
        </section>

        <section className="card wig-card">
          <h2>Une perruque qui vous ressemble</h2>
          <p>Une photo suffit : nous analysons la forme de votre visage et votre teint pour vous proposer les coupes et les couleurs qui vous iront le mieux.</p>
          <a className="btn primary" href="#/wigs"><Icon name="camera" size={18} /> Essayer</a>
        </section>

        <section className="card">
          <h3>Prochain rendez-vous</h3>
          {appt ? (
            <div className="appt">
              <span className="appt-date">
                <span className="d">{new Date(appt.starts_at).getDate()}</span>
                <span className="m">{fmtDate(appt.starts_at).split(" ")[1]}</span>
              </span>
              <div>
                <p><strong>{KINDS[appt.kind] || appt.kind}</strong> avec {appt.doctor_name}</p>
                <p className="muted small">{fmtDate(appt.starts_at, true)} · {relDays(appt.starts_at)}</p>
                {appt.notes && <p className="small">{appt.notes}</p>}
              </div>
            </div>
          ) : <p className="muted">Aucun rendez-vous prévu.</p>}
          <a className="link" href="#/doctor-contact">Écrire à {doctor ? doctor.full_name : "mon médecin"}</a>
        </section>

        <section className="card">
          <h3>Dernier compte rendu</h3>
          {rep ? (
            <>
              <p><TriageBadge level={rep.triage} /> <span className="muted small">le {fmtDate(rep.created_at)}</span></p>
              <p className="small">{rep.reviewed ? "Lu par votre médecin." : "En attente de lecture par votre médecin."}</p>
              {rep.doctor_comment && <p className="doctor-quote">« {rep.doctor_comment} »</p>}
              <a className="link" href={`#/reports/${rep.id}`}>Voir le compte rendu</a>
            </>
          ) : (
            <p className="muted">Après votre première autopalpation, répondez au questionnaire : votre médecin recevra un compte rendu.</p>
          )}
        </section>

        <section className="card ask-card">
          <h3>Une question ?</h3>
          <p className="small">L'assistante répond à partir d'un corpus médical sur le cancer du sein, avec ses sources.</p>
          <div className="chips">
            {["Comment faire l'autopalpation ?", "Que faire en cas de fièvre sous chimio ?", "Quand choisir ma perruque ?"].map((q) => (
              <a key={q} className="chip" href={`#/chat?q=${encodeURIComponent(q)}`}>{q}</a>
            ))}
          </div>
          {profile.treatment && <p className="muted tiny">Traitement en cours : {profile.treatment}</p>}
        </section>
      </div>
    </div>
  );
}
