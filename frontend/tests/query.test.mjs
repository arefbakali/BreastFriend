// Cache de données partagé (src/lib/query.js)
import assert from "node:assert/strict";
import test from "node:test";
import { clearQueries, fetchQuery, getQueryData, invalidate, setDefaultFetcher, setQueryData, subscribeQuery } from "../src/lib/query.js";
import { EVENT_KEYS, keysForMutation } from "../src/lib/invalidation.js";

test("requêtes simultanées dédupliquées", async () => {
  clearQueries();
  let calls = 0;
  setDefaultFetcher(async (k) => { calls += 1; await new Promise((r) => setTimeout(r, 5)); return { k, calls }; });
  await Promise.all([fetchQuery("/notifications"), fetchQuery("/notifications"), fetchQuery("/notifications")]);
  assert.equal(calls, 1);
  assert.equal(getQueryData("/notifications").k, "/notifications");
});

test("invalidation par préfixe (y compris paramètres et sous-chemins)", async () => {
  clearQueries();
  for (const k of ["/doctor/patients?q=", "/doctor/patients/4", "/doctor/patients/4/messages", "/doctor/patientsX", "/rag/status"]) {
    setQueryData(k, { v: 1 });
  }
  const refetched = [];
  setDefaultFetcher(async (k) => { refetched.push(k); return {}; });
  // entrées « affichées » (abonnées) sauf /doctor/patients/4 qui n'est plus à l'écran
  const offs = ["/doctor/patients?q=", "/doctor/patients/4/messages", "/doctor/patientsX", "/rag/status"]
    .map((k) => subscribeQuery(k, () => {}));
  invalidate("/doctor/patients");
  await new Promise((r) => setTimeout(r, 0));          // rechargement asynchrone
  assert.deepEqual(refetched.sort(), ["/doctor/patients/4/messages", "/doctor/patients?q="]);
  offs.forEach((off) => off());
});

test("mise à jour optimiste", () => {
  clearQueries();
  setQueryData("/patient/messages", { messages: [{ id: 1 }] });
  setQueryData("/patient/messages", (d) => ({ messages: [...d.messages, { id: "tmp" }] }));
  assert.equal(getQueryData("/patient/messages").messages.length, 2);
});

test("table d'invalidation : les écritures touchent les bonnes données", () => {
  assert.ok(keysForMutation("/doctor/appointments/12").includes("/patient/appointments"));
  assert.ok(keysForMutation("/doctor/patients/3/messages").includes("/doctor/patients"));
  assert.ok(keysForMutation("/doctor/reports/8").includes("/doctor/dashboard"));
  assert.ok(keysForMutation("/patient/questionnaire").includes("/patient/reports"));
  assert.ok(keysForMutation("/notifications/read").includes("/notifications"));
  assert.ok(EVENT_KEYS.message.includes("/patient/messages"));
  assert.ok(EVENT_KEYS.appointment.includes("/doctor/appointments"));
});
