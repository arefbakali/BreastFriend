import React from "react";
import { openPdf } from "../api.js";
import { toast } from "./ui.jsx";
import { fmtDate } from "../utils.js";
import { TriageBadge } from "./ui.jsx";

const VAL = { yes: "Oui", no: "Non", unknown: "Incertain" };

export default function ReportView({ report, forDoctor = false, questions = [] }) {
  const rep = report.report;
  const byText = Object.fromEntries(questions.map((q) => [q.text, q]));
  return (
    <article className="report">
      <header className={`report-head t-${report.triage}`}>
        <div>
          <p className="muted small">Compte rendu du {fmtDate(report.created_at, true)}</p>
          <h2>{rep.patient?.name}</h2>
        </div>
        <div className="report-head-right">
          <TriageBadge level={report.triage} />
          {forDoctor && <span className="score" title="Score de vigilance">Score {report.risk_score}</span>}
          <button className="btn ghost small" onClick={() => openPdf(report.id).catch((e) => toast(e.message, "err"))}>Ouvrir le PDF</button>
          <button className="btn ghost small" onClick={() => openPdf(report.id, true).catch((e) => toast(e.message, "err"))}>Télécharger</button>
        </div>
      </header>

      <section className="report-summary">
        <h3>Synthèse</h3>
        <p>{rep.summary}</p>
        {forDoctor && rep.triage.flags.length > 0 && (
          <div className="flags">
            {rep.triage.flags.map((f) => <span key={f.category} className={`flag w${Math.min(f.weight, 3)}`}>{f.label}</span>)}
          </div>
        )}
        <p className="muted tiny">Rédigée {rep.generated_by === "llm" ? "par le LLM à partir des réponses" : "automatiquement par règles"}.</p>
      </section>

      <section>
        <h3>Détail par section</h3>
        <div className="report-sections">
          {rep.sections.map((s) => (
            <div key={s.title} className={`rsec ${s.alert ? "alert" : ""}`}>
              <h4>{s.title}</h4>
              {s.findings.map((f, i) => {
                const q = byText[f.question];
                return (
                  <div key={i} className="finding">
                    <span className={`ans a-${f.value}`}>{VAL[f.value]}</span>
                    <div>
                      <p>{f.question}</p>
                      {f.detail && <p className="detail">« {f.detail} »</p>}
                      {forDoctor && q?.rationale && (
                        <p className="rationale tiny">Source : {q.rationale.title} — {q.rationale.section}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </section>

      {forDoctor && (
        <section>
          <h3>Conduite proposée</h3>
          <ul className="plain">{rep.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
          {rep.triage.notes.length > 0 && <ul className="plain muted">{rep.triage.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        </section>
      )}
      {report.doctor_comment && (
        <section className="doctor-comment">
          <h3>Commentaire du médecin</h3>
          <p>{report.doctor_comment}</p>
        </section>
      )}
      <p className="muted tiny">{rep.disclaimer}</p>
    </article>
  );
}
