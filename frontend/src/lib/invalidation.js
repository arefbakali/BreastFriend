// Quelles données deviennent périmées après une écriture ? Table unique utilisée
// (1) après chaque mutation réussie de l'utilisatrice et (2) à chaque événement temps réel
// reçu d'un autre utilisateur (message, rendez-vous, compte rendu…).

const DASH = ["/doctor/dashboard", "/patient/dashboard"];

// mutation : [expression sur le chemin, clés à invalider]
const MUTATION_RULES = [
  [/^\/doctor\/appointments|^\/patient\/appointments/, ["/doctor/appointments", "/patient/appointments", "/doctor/patients", "/notifications", ...DASH]],
  [/\/messages$/, ["/patient/messages", "/doctor/patients", "/notifications", ...DASH]],
  [/^\/notifications/, ["/notifications", ...DASH]],
  [/^\/doctor\/reports/, ["/doctor/reports", "/doctor/patients", "/notifications", ...DASH]],
  [/^\/doctor\/patients\/\d+\/questions/, ["/doctor/patients", "/patient/questionnaire"]],
  [/^\/doctor\/patients\/\d+$/, ["/doctor/patients", "/doctor/dashboard"]],
  [/^\/patient\/questionnaire/, ["/patient/questionnaire", "/patient/reports", "/notifications", ...DASH]],
  [/^\/patient\/self-exam/, ["/patient/dashboard"]],
  [/^\/patient\/profile|^\/auth\/me/, ["/patient/dashboard", "/auth/me"]],
  [/^\/doctor\/notes/, ["/doctor/notes"]],
  [/^\/rag\//, ["/rag/"]],
  [/^\/wigs\//, ["/wigs/last"]],
  [/^\/chat/, ["/chat/history"]],
];

export function keysForMutation(path) {
  const clean = path.split("?")[0];
  const keys = new Set();
  for (const [re, ks] of MUTATION_RULES) if (re.test(clean)) ks.forEach((k) => keys.add(k));
  return [...keys];
}

// événements SSE envoyés par le backend (voir backend/events.py)
export const EVENT_KEYS = {
  notification: ["/notifications", ...DASH],
  message: ["/patient/messages", "/doctor/patients", "/notifications", ...DASH],
  appointment: ["/doctor/appointments", "/patient/appointments", "/doctor/patients", ...DASH],
  report: ["/doctor/reports", "/patient/reports", "/doctor/patients", "/notifications", ...DASH],
  question_set: ["/patient/questionnaire", "/doctor/patients"],
  patient: ["/doctor/patients", ...DASH],
  // la page Corpus applique elle-même chaque changement d'état (barre de progression fluide)
  rag_document: [],
  rag_status: ["/rag/status", "/rag/documents"],
};
