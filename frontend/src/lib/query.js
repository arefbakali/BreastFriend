// Cache partagé des données serveur (même principe que TanStack Query, sans dépendance).
//
// Pourquoi : auparavant chaque composant gardait sa propre copie (useFetch isolé). Une
// modification faite à un endroit ne mettait pas à jour les autres copies -> F5 nécessaire.
// Ici, une même clé (le chemin d'API) = une seule entrée partagée par tous les composants.
//   - requêtes identiques simultanées dédupliquées ;
//   - après une mutation ou un événement temps réel : invalidate(prefix) -> rechargement
//     en arrière-plan des données affichées (l'ancienne valeur reste visible, pas de clignotement) ;
//   - rechargement au retour sur l'onglet et au retour du réseau.
import { useCallback, useEffect, useSyncExternalStore } from "react";

const entries = new Map();
let defaultFetcher = null;
const STALE_MS = 30_000;

export function setDefaultFetcher(fn) {
  defaultFetcher = fn;
}

function entry(key) {
  let e = entries.get(key);
  if (!e) {
    e = { key, data: undefined, error: null, updatedAt: 0, promise: null, listeners: new Set(), fetcher: null,
          snapshot: null, version: 0 };
    entries.set(key, e);
  }
  return e;
}

function emit(e) {
  e.version += 1;
  e.snapshot = null;
  e.listeners.forEach((l) => l());
}

function snapshot(e) {
  if (!e.snapshot) {
    e.snapshot = { data: e.data, error: e.error, fetching: !!e.promise, updatedAt: e.updatedAt };
  }
  return e.snapshot;
}

export function fetchQuery(key, fetcher) {
  const e = entry(key);
  if (fetcher) e.fetcher = fetcher;
  if (e.promise) return e.promise;              // dédoublonnage
  const fn = e.fetcher || defaultFetcher;
  e.promise = Promise.resolve()
    .then(() => fn(key))
    .then(
      (data) => { e.data = data; e.error = null; e.updatedAt = Date.now(); },
      (err) => { e.error = err; e.updatedAt = Date.now(); },
    )
    .finally(() => { e.promise = null; emit(e); });
  emit(e);
  return e.promise;
}

/** Abonnement à une clé (utilisé par useQuery). Renvoie la fonction de désabonnement. */
export function subscribeQuery(key, cb) {
  const e = entry(key);
  e.listeners.add(cb);
  return () => e.listeners.delete(cb);
}

export function getQueryData(key) {
  return entries.get(key)?.data;
}

export function setQueryData(key, updater) {
  const e = entry(key);
  e.data = typeof updater === "function" ? updater(e.data) : updater;
  e.updatedAt = Date.now();
  emit(e);
}

const matches = (key, prefix) => key === prefix || key.startsWith(prefix.endsWith("/") ? prefix : `${prefix}/`)
  || key.startsWith(`${prefix}?`);

/** Marque périmées les clés commençant par l'un des préfixes et recharge celles affichées. */
export function invalidate(...prefixes) {
  for (const e of entries.values()) {
    if (!prefixes.some((p) => matches(e.key, p))) continue;
    e.updatedAt = 0;
    if (e.listeners.size) fetchQuery(e.key);
  }
}

export function invalidateAll() {
  for (const e of entries.values()) {
    e.updatedAt = 0;
    if (e.listeners.size) fetchQuery(e.key);
  }
}

export function clearQueries() {
  entries.clear();
}

/**
 * useQuery(key, { fetcher, enabled, staleMs })
 * -> { data, error, loading (aucune donnée encore), fetching, refetch, setData }
 */
export function useQuery(key, { fetcher, enabled = true, staleMs = STALE_MS } = {}) {
  const active = enabled && !!key;
  const e = active ? entry(key) : null;
  if (e && fetcher) e.fetcher = fetcher;
  const subscribe = useCallback((cb) => (e ? subscribeQuery(e.key, cb) : () => {}), [e]);
  const snap = useSyncExternalStore(subscribe, () => (e ? snapshot(e) : EMPTY), () => EMPTY);

  useEffect(() => {
    if (!e) return;
    if (!e.promise && (e.data === undefined || Date.now() - e.updatedAt > staleMs)) fetchQuery(key);
  }, [e, key, staleMs]);

  const refetch = useCallback(() => (key ? fetchQuery(key) : Promise.resolve()), [key]);
  const setData = useCallback((u) => key && setQueryData(key, u), [key]);
  return {
    data: snap.data,
    error: snap.error,
    loading: active && snap.data === undefined && !snap.error,
    fetching: snap.fetching,
    refetch,
    setData,
  };
}

const EMPTY = { data: undefined, error: null, fetching: false, updatedAt: 0 };

// Retour sur l'onglet / retour du réseau : on rafraîchit ce qui est affiché et périmé.
if (typeof window !== "undefined") {
  const refreshVisible = () => {
    for (const e of entries.values()) {
      if (e.listeners.size && Date.now() - e.updatedAt > 5_000) fetchQuery(e.key);
    }
  };
  window.addEventListener("focus", refreshVisible);
  window.addEventListener("online", refreshVisible);
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && refreshVisible());
}
