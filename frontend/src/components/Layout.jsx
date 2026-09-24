import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useRealtime } from "../lib/realtime.jsx";
import { useAuth } from "../auth.jsx";
import { navigate } from "../router.js";
import { fmtDate } from "../utils.js";
import Icon from "./icons.jsx";
import { Avatar, useFetch } from "./ui.jsx";

const NAV = {
  patient: [
    ["/home", "Accueil", "home"],
    ["/self-exam", "Autopalpation", "hand"],
    ["/questionnaire", "Questionnaire", "clipboard"],
    ["/chat", "Assistante", "chat"],
    ["/wigs", "Ma perruque", "wig"],
    ["/reports", "Comptes rendus", "file"],
    ["/doctor-contact", "Mon médecin", "doctor"],
  ],
  doctor: [
    ["/doctor", "Accueil", "home"],
    ["/doctor/patients", "Patientes", "users"],
    ["/doctor/calendar", "Agenda", "calendar"],
    ["/doctor/notifications", "Notifications", "bell"],
    ["/doctor/corpus", "Corpus médical", "book"],
    ["/chat", "Assistante", "chat"],
  ],
};

function Bell() {
  const [open, setOpen] = useState(false);
  // même donnée que la page Notifications et le tableau de bord : une seule copie partagée,
  // mise à jour par les événements temps réel (plus de sondage toutes les 30 s)
  const q = useFetch("/notifications");
  const data = q.data || { notifications: [], unread: 0 };
  const ref = useRef(null);
  useEffect(() => {
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const go = async (n) => {
    setOpen(false);
    if (n.link) navigate(n.link);
    if (!n.is_read) {
      q.setData((d) => d && { ...d, unread: Math.max(0, d.unread - 1),
        notifications: d.notifications.map((x) => (x.id === n.id ? { ...x, is_read: 1 } : x)) });
      api("/notifications/read", { method: "POST", body: { ids: [n.id] } })
        .catch((err) => { console.warn("Notification non marquée comme lue", err); q.reload(); });
    }
  };
  return (
    <div className="bell" ref={ref}>
      <button className="icon-btn bell-btn" onClick={() => setOpen(!open)} aria-label={`Notifications (${data.unread} non lues)`}>
        <Icon name="bell" />
        {data.unread > 0 && <span className="bell-count">{data.unread}</span>}
      </button>
      {open && (
        <div className="bell-panel">
          <div className="bell-head">
            <strong>Notifications</strong>
            {data.unread > 0 && (
              <button className="link" onClick={() => api("/notifications/read", { method: "POST", body: {} }).catch((err) => console.warn(err))}>
                Tout marquer comme lu
              </button>
            )}
          </div>
          {data.notifications.length === 0 && <p className="muted small pad">Aucune notification.</p>}
          <ul>
            {data.notifications.slice(0, 12).map((n) => (
              <li key={n.id}>
                <button className={`notif ${n.is_read ? "" : "unread"} k-${n.kind}`} onClick={() => go(n)}>
                  <span className="notif-title">{n.title}</span>
                  {n.body && <span className="notif-body">{n.body}</span>}
                  <span className="notif-date">{fmtDate(n.created_at, true)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function LiveStatus() {
  const { status } = useRealtime();
  if (status === "live") return <span className="live-dot" title="Mises à jour en direct actives" aria-label="En direct" />;
  if (status === "retrying") return <span className="live-dot off" title="Reconnexion au serveur…">Reconnexion…</span>;
  return null;
}

export default function Layout({ path, title, children }) {
  const { user, logout } = useAuth();
  const [menu, setMenu] = useState(false);
  const items = NAV[user.role];
  const active = (to) => path === to || (to !== "/doctor" && to !== "/home" && path.startsWith(to + "/")) ||
    (to === "/doctor/patients" && path.startsWith("/doctor/reports"));
  useEffect(() => setMenu(false), [path]);
  return (
    <div className={`shell ${menu ? "menu-open" : ""}`}>
      <aside className="sidebar">
        <a className="brand" href={user.role === "doctor" ? "#/doctor" : "#/home"}>
          <img src="/logo.png" alt="" />
          <span>BreastFriend</span>
        </a>
        <nav aria-label="Navigation principale">
          {items.map(([to, label, icon]) => (
            <a key={to} href={`#${to}`} className={active(to) ? "nav-link active" : "nav-link"} aria-current={active(to) ? "page" : undefined}>
              <Icon name={icon} /> {label}
            </a>
          ))}
        </nav>
        <button className="nav-link logout" onClick={logout}>
          <Icon name="logout" /> Se déconnecter
        </button>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenu(!menu)} aria-label="Menu"><Icon name="menu" /></button>
          <h1>{title}</h1>
          <div className="topbar-right">
            <LiveStatus />
            <Bell />
            <div className="me">
              <Avatar src={user.avatar} name={user.full_name} size={36} />
              <div>
                <span className="me-name">{user.full_name}</span>
                <span className="me-role">{user.role === "doctor" ? user.specialty || "Médecin" : "Patiente"}</span>
              </div>
            </div>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
      {menu && <div className="scrim" onClick={() => setMenu(false)} />}
    </div>
  );
}
