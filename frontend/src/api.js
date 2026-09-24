// Client HTTP : jeton de session, erreurs JSON de l'API Flask, invalidation du cache
// partagé après chaque écriture réussie, envoi de fichier avec progression, streaming.
import { invalidate, setDefaultFetcher } from "./lib/query.js";
import { keysForMutation } from "./lib/invalidation.js";

const TOKEN_KEY = "bf_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const OFFLINE = "Serveur injoignable : vérifiez que le backend Flask est lancé (python app.py).";

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleAuthFailure(status) {
  if (status === 401 && getToken()) {
    setToken(null);
    window.dispatchEvent(new Event("bf:logout"));
  }
}

export async function api(path, { method = "GET", body, form, signal } = {}) {
  const headers = authHeaders();
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload, signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(OFFLINE, 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    handleAuthFailure(res.status);
    throw new ApiError(data.error || `Erreur ${res.status}`, res.status, data);
  }
  if (method !== "GET") {
    const keys = keysForMutation(path);
    if (keys.length) invalidate(...keys);
  }
  return data;
}

setDefaultFetcher((key) => api(key));

/** Envoi de fichier avec progression (fetch ne fournit pas la progression d'envoi). */
export function upload(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    Object.entries(authHeaders()).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(OFFLINE, 0));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch { data = {}; }
      if (xhr.status >= 200 && xhr.status < 300) {
        invalidate(...keysForMutation(path));
        resolve(data);
      } else {
        handleAuthFailure(xhr.status);
        reject(new ApiError(data.error || `Erreur ${xhr.status}`, xhr.status, data));
      }
    };
    xhr.send(form);
  });
}

/** Jeton court à usage limité pour les URL (flux SSE, lien PDF) : le jeton de session
 *  n'apparaît jamais dans une URL ni dans les journaux du serveur. */
export async function ticket(purpose) {
  return (await api("/tickets", { method: "POST", body: { purpose } })).ticket;
}

export async function openPdf(id, download = false) {
  // fenêtre ouverte immédiatement (geste utilisateur) pour ne pas être bloquée
  const win = download ? null : window.open("about:blank", "_blank");
  try {
    const t = await ticket("pdf");
    const url = `/api/reports/${id}/pdf?ticket=${encodeURIComponent(t)}${download ? "&download=1" : ""}`;
    if (win) win.location.href = url;
    else {
      const a = document.createElement("a");
      a.href = url;
      a.download = `compte-rendu-${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
  } catch (err) {
    win?.close();
    throw err;
  }
}

/** Lecture d'une réponse NDJSON en streaming : onEvent({type, ...}) pour chaque ligne. */
export async function streamChat(message, onEvent, signal) {
  let res;
  try {
    res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(OFFLINE, 0);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    handleAuthFailure(res.status);
    throw new ApiError(data.error || `Erreur ${res.status}`, res.status, data);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
  invalidate("/chat/history");
}
