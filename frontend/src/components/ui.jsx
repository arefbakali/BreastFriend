import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "../lib/query.js";
import { TRIAGE, initials } from "../utils.js";

/** Données serveur partagées (voir lib/query.js). La clé est le chemin d'API complet :
 *  tous les composants qui affichent la même ressource partagent la même copie. */
export function useFetch(path) {
  const q = useQuery(path || null);
  return { data: q.data ?? null, error: q.error ? q.error.message : null, loading: q.loading,
           fetching: q.fetching, reload: q.refetch, setData: q.setData };
}

export function Avatar({ src, name, size = 44 }) {
  const [broken, setBroken] = useState(false);
  if (src && !broken)
    return <img className="avatar" src={src} alt="" width={size} height={size} style={{ width: size, height: size }} onError={() => setBroken(true)} />;
  return (
    <span className="avatar avatar-fallback" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function TriageBadge({ level, reviewed }) {
  if (!level) return <span className="badge muted">Aucun compte rendu</span>;
  const t = TRIAGE[level];
  return (
    <span className={`badge ${reviewed ? "muted" : t.cls}`}>
      {t.label}
      {reviewed ? " · lu" : ""}
    </span>
  );
}

export function Spinner({ label = "Chargement…" }) {
  return (
    <div className="spinner" role="status">
      <span className="dot" /> <span className="dot" /> <span className="dot" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorBox({ children, message, onRetry }) {
  const content = children ?? message;
  if (!content) return null;
  return (
    <div className="error-box" role="alert">
      <span>{content}</span>
      {onRetry && <button className="btn ghost small" onClick={() => onRetry()}>Réessayer</button>}
    </div>
  );
}

/** Squelette de chargement (évite les pages blanches pendant le premier chargement). */
export function Skeleton({ lines = 3, height = 14 }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} style={{ height, width: `${92 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  );
}

export function Empty({ title, children, action }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Modal({ title, onClose, children, width = 520 }) {
  const ref = useRef(null);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: width }} tabIndex={-1} ref={ref}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Fermer">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

let pushToast = () => {};
export const toast = (msg, kind = "ok") => pushToast({ msg, kind, id: Math.random() });

export function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    pushToast = (t) => {
      setItems((l) => [...l, t]);
      setTimeout(() => setItems((l) => l.filter((x) => x.id !== t.id)), 3800);
    };
  }, []);
  return (
    <div className="toaster" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([key, label, count]) => (
        <button key={key} role="tab" aria-selected={value === key} className={value === key ? "tab active" : "tab"} onClick={() => onChange(key)}>
          {label}
          {count ? <span className="tab-count">{count}</span> : null}
        </button>
      ))}
    </div>
  );
}
