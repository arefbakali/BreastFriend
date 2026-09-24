// Connexion temps réel (Server-Sent Events) : une par onglet, ouverte après la connexion.
// Chaque événement invalide les données concernées ; le composant qui les affiche se met
// à jour tout seul. EventSource ne peut pas envoyer d'en-tête : on obtient un jeton court
// (2 min) avant chaque (re)connexion.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ticket } from "../api.js";
import { EVENT_KEYS } from "./invalidation.js";
import { invalidate, invalidateAll } from "./query.js";

const RealtimeContext = createContext({ status: "off", subscribe: () => () => {} });

export function RealtimeProvider({ user, children }) {
  const [status, setStatus] = useState("off");        // off | connecting | live | retrying
  const listeners = useRef(new Set());

  useEffect(() => {
    if (!user) return undefined;
    let es = null;
    let stopped = false;
    let retry = null;
    let attempt = 0;
    let wasLive = false;

    const dispatch = (type, raw) => {
      let data = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch (err) { console.warn("Événement illisible", type, err); }
      if (EVENT_KEYS[type]) invalidate(...EVENT_KEYS[type]);
      listeners.current.forEach((fn) => fn(type, data));
    };

    const connect = async () => {
      if (stopped) return;
      setStatus(attempt ? "retrying" : "connecting");
      let t;
      try {
        t = await ticket("events");
      } catch (err) {
        console.warn("Temps réel : jeton indisponible", err.message);
        return schedule();
      }
      if (stopped) return;
      es = new EventSource(`/api/events?ticket=${encodeURIComponent(t)}`);
      es.addEventListener("ready", () => {
        setStatus("live");
        attempt = 0;
        // après une coupure, des événements ont pu être manqués : on rafraîchit l'affiché
        if (wasLive) invalidateAll();
        wasLive = true;
      });
      Object.keys(EVENT_KEYS).forEach((type) => es.addEventListener(type, (ev) => dispatch(type, ev.data)));
      es.onerror = () => {
        // le jeton de l'URL expire : on referme et on se reconnecte avec un nouveau jeton
        es.close();
        schedule();
      };
    };

    const schedule = () => {
      if (stopped) return;
      setStatus("retrying");
      attempt += 1;
      retry = setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4)));
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      es?.close();
      setStatus("off");
    };
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps -- reconnexion seulement si l'utilisateur change

  const subscribe = useCallback((fn) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);
  const value = useMemo(() => ({ status, subscribe }), [status, subscribe]);
  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export const useRealtime = () => useContext(RealtimeContext);

/** Réagit à un type d'événement (ex. mise à jour d'une barre de progression). */
export function useRealtimeEvent(type, handler) {
  const { subscribe } = useRealtime();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((t, data) => t === type && ref.current(data)), [subscribe, type]);
}
