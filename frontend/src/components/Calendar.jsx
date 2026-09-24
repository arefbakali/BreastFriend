import React, { useMemo, useState } from "react";
import { KINDS, MONTHS, iso } from "../utils.js";

const DAYS = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];

function startOfWeek(d) {
  const x = new Date(d);
  x.setDate(x.getDate() - x.getDay());
  x.setHours(0, 0, 0, 0);
  return x;
}

// Calendrier mois / semaine / jour (comme la maquette « Appointments Calendar »).
export default function Calendar({ events = [], onSelect, onDayClick, compact = false }) {
  const [view, setView] = useState("month");
  const [cursor, setCursor] = useState(() => new Date());
  const byDay = useMemo(() => {
    const m = {};
    events.forEach((e) => (m[e.starts_at.slice(0, 10)] ||= []).push(e));
    return m;
  }, [events]);
  const today = iso(new Date());

  const shift = (n) => {
    const d = new Date(cursor);
    if (view === "month") d.setMonth(d.getMonth() + n);
    else if (view === "week") d.setDate(d.getDate() + 7 * n);
    else d.setDate(d.getDate() + n);
    setCursor(d);
  };

  let days = [];
  if (view === "month") {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const start = startOfWeek(first);
    for (let i = 0; i < 42; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      days.push(d);
    }
    if (days[35].getMonth() !== cursor.getMonth()) days = days.slice(0, 35);
  } else if (view === "week") {
    const start = startOfWeek(cursor);
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      days.push(d);
    }
  } else days = [new Date(cursor)];

  const title =
    view === "day"
      ? `${DAYS[cursor.getDay()]} ${cursor.getDate()} ${MONTHS[cursor.getMonth()]}`
      : `${MONTHS[cursor.getMonth()]} ${cursor.getFullYear()}`;

  return (
    <div className={`calendar ${compact ? "compact" : ""} view-${view}`}>
      <div className="cal-head">
        <div className="cal-nav">
          <button className="icon-btn" onClick={() => shift(-1)} aria-label="Précédent">‹</button>
          <button className="icon-btn" onClick={() => shift(1)} aria-label="Suivant">›</button>
          <button className="link small" onClick={() => setCursor(new Date())}>Aujourd'hui</button>
        </div>
        <strong className="cal-title">{title}</strong>
        <div className="seg" role="group" aria-label="Vue">
          {[["month", "Mois"], ["week", "Semaine"], ["day", "Jour"]].map(([k, l]) => (
            <button key={k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
      </div>
      {view !== "day" && (
        <div className="cal-grid cal-dow">{DAYS.map((d) => <span key={d}>{d}</span>)}</div>
      )}
      <div className={view === "day" ? "cal-day" : "cal-grid"}>
        {days.map((d) => {
          const key = iso(d);
          const evs = (byDay[key] || []).sort((a, b) => a.starts_at.localeCompare(b.starts_at));
          const out = view === "month" && d.getMonth() !== cursor.getMonth();
          return (
            <div key={key} className={`cal-cell ${out ? "out" : ""} ${key === today ? "today" : ""}`}
              onClick={() => onDayClick?.(key)}>
              {view !== "day" && <span className="cal-num">{d.getDate()}</span>}
              <div className="cal-events">
                {evs.slice(0, view === "month" ? (compact ? 2 : 3) : 20).map((e) => (
                  <button key={e.id} className={`cal-ev k-${e.kind} ${e.status}`} title={`${e.starts_at.slice(11, 16)} ${e.patient_name || ""}`}
                    onClick={(ev) => { ev.stopPropagation(); onSelect?.(e); }}>
                    <span className="t">{e.starts_at.slice(11, 16)}</span>
                    {!compact || view !== "month" ? <span className="n">{e.patient_name} · {KINDS[e.kind] || e.kind}</span> : null}
                  </button>
                ))}
                {view === "month" && evs.length > (compact ? 2 : 3) && <span className="more">+{evs.length - (compact ? 2 : 3)}</span>}
                {view === "day" && evs.length === 0 && <p className="muted small">Aucun rendez-vous ce jour.</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
