import React, { useState } from "react";
import { api } from "../api.js";
import { navigate } from "../router.js";
import { ErrorBox, Spinner, toast, useFetch } from "../components/ui.jsx";
import { fmtDate } from "../utils.js";

const STEPS = [
  {
    title: "Observer devant le miroir",
    text: "Torse nu, bras le long du corps, regardez la taille, la forme et la symétrie de vos seins, la couleur de la peau et l'aspect des mamelons. Levez ensuite les bras, puis posez les mains sur les hanches en contractant la poitrine.",
    look: ["Un creux, une ride ou une peau qui se rétracte", "Une rougeur ou un aspect de peau d'orange", "Un mamelon qui rentre vers l'intérieur"],
  },
  {
    title: "Palper chaque sein",
    text: "Allongée ou sous la douche, levez un bras derrière la tête. Avec la pulpe des trois doigts du milieu de l'autre main, faites de petits cercles en appuyant légèrement, puis moyennement, puis fermement. Parcourez tout le sein, de la clavicule au pli sous le sein et du sternum à l'aisselle.",
    look: ["Une boule ou un épaississement nouveau", "Une zone qui diffère de l'autre sein", "Une douleur localisée qui persiste"],
  },
  {
    title: "L'aisselle et le mamelon",
    text: "Palpez le creux de l'aisselle à la recherche d'un ganglion gonflé. Observez le mamelon : un écoulement apparaît-il spontanément ? Recommencez de l'autre côté.",
    look: ["Un ganglion dur sous le bras", "Un écoulement, surtout clair ou sanglant", "Des croûtes ou une plaie qui ne guérit pas"],
  },
];

export default function SelfExam() {
  const { data, error, loading, reload } = useFetch("/patient/dashboard");
  const [step, setStep] = useState(0);
  const [day, setDay] = useState(null);
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const reminder = day ?? data.profile.reminder_day ?? 1;
  const s = STEPS[step];

  const done = async () => {
    setBusy(true);
    try {
      await api("/patient/self-exam", { method: "POST" });
      toast("Autopalpation enregistrée. Passons au questionnaire.");
      navigate("/questionnaire");
    } catch (e) { toast(e.message, "err"); } finally { setBusy(false); }
  };
  const saveDay = async () => {
    try {
      await api("/patient/profile", { method: "PUT", body: { reminder_day: Number(reminder) } });
      toast("Jour de rappel enregistré.");
      reload();
    } catch (e) { toast(e.message, "err"); }
  };

  return (
    <div className="selfexam">
      <p className="lead">Une fois par mois, environ une semaine après le début des règles (ou à date fixe après la ménopause). Comptez cinq minutes.</p>
      <ol className="stepper" aria-label="Étapes">
        {STEPS.map((st, i) => (
          <li key={st.title}>
            <button className={i === step ? "on" : i < step ? "done" : ""} onClick={() => setStep(i)}>
              <span className="n">{i + 1}</span> {st.title}
            </button>
          </li>
        ))}
      </ol>
      <section className="card step-card">
        <div className="step-art" aria-hidden="true"><img src={`/step${step + 1}.svg`} alt="" /></div>
        <div>
          <h2>{s.title}</h2>
          <p>{s.text}</p>
          <h4>Ce qui doit vous amener à consulter</h4>
          <ul className="plain dots">{s.look.map((l) => <li key={l}>{l}</li>)}</ul>
          <div className="actions">
            {step > 0 && <button className="btn ghost" onClick={() => setStep(step - 1)}>Étape précédente</button>}
            {step < STEPS.length - 1 ? (
              <button className="btn primary" onClick={() => setStep(step + 1)}>Étape suivante</button>
            ) : (
              <button className="btn primary" onClick={done} disabled={busy}>J'ai terminé mon autopalpation</button>
            )}
          </div>
        </div>
      </section>
      <div className="split">
        <section className="card">
          <h3>Mon rappel mensuel</h3>
          <p className="small">Dernière autopalpation : {data.profile.last_self_exam ? fmtDate(data.profile.last_self_exam) : "jamais enregistrée"}.</p>
          <div className="inline-form">
            <label>Me le rappeler le
              <select value={reminder} onChange={(e) => setDay(e.target.value)}>
                {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              de chaque mois
            </label>
            <button className="btn ghost small" onClick={saveDay}>Enregistrer</button>
          </div>
        </section>
        <section className="card soft">
          <h3>Pas de panique</h3>
          <p className="small">La plupart des boules découvertes sont bénignes (kystes, adénofibromes). Mais tout changement nouveau doit être montré à un médecin : notez le côté, l'emplacement et la date, puis répondez au questionnaire.</p>
        </section>
      </div>
    </div>
  );
}
