export const TRIAGE = {
  rassurant: { label: "Rassurant", cls: "ok" },
  a_surveiller: { label: "À surveiller", cls: "warn" },
  urgent: { label: "Prioritaire", cls: "alert" },
};

export const STATUS = { prevention: "Prévention", traitement: "En traitement", remission: "Rémission / suivi" };

export const KINDS = {
  consultation: "Consultation",
  "check-in": "Check-in",
  mammographie: "Mammographie",
  chimiotherapie: "Chimiothérapie",
};

const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

export function toDate(v) {
  if (!v) return null;
  return new Date(v.includes("T") ? v : v.replace(" ", "T"));
}

export function fmtDate(v, withTime = false) {
  const d = toDate(v);
  if (!d || isNaN(d)) return "—";
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  return withTime ? `${base} à ${String(d.getHours()).padStart(2, "0")}h${String(d.getMinutes()).padStart(2, "0")}` : base;
}

export function relDays(v) {
  const d = toDate(v);
  if (!d) return "";
  const a = new Date(); a.setHours(0, 0, 0, 0);
  const b = new Date(d); b.setHours(0, 0, 0, 0);
  const n = Math.round((b - a) / 86400000);
  if (n === 0) return "aujourd'hui";
  if (n === 1) return "demain";
  if (n === -1) return "hier";
  return n > 0 ? `dans ${n} jours` : `il y a ${-n} jours`;
}

export const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const initials = (name = "") =>
  name.replace(/^Dr\.?\s+/i, "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

export { MONTHS };
