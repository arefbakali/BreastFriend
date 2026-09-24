import React from "react";
import { api } from "../api.js";
import { Empty, ErrorBox, Spinner, useFetch } from "../components/ui.jsx";
import { navigate } from "../router.js";
import { fmtDate } from "../utils.js";

const KIND = { report: "Compte rendu", checkin: "Check-in", message: "Message", appointment: "Rendez-vous", patient: "Patiente", questionnaire: "Questionnaire" };

export default function Notifications() {
  const { data, error, loading, reload } = useFetch("/notifications");
  if (loading && !data) return <Spinner />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const open = async (n) => {
    await api("/notifications/read", { method: "POST", body: { ids: [n.id] } });
    if (n.link) navigate(n.link); else reload();
  };
  if (!data.notifications.length) return <Empty title="Aucune notification" />;
  return (
    <div>
      <div className="toolbar">
        <p className="small muted">{data.unread} non lue{data.unread > 1 ? "s" : ""}</p>
        {data.unread > 0 && <button className="btn ghost small" onClick={() => api("/notifications/read", { method: "POST", body: {} }).then(reload)}>Tout marquer comme lu</button>}
      </div>
      <div className="list">
        {data.notifications.map((n) => (
          <button key={n.id} className={`row-item notif-row ${n.is_read ? "" : "unread"} k-${n.kind}`} onClick={() => open(n)}>
            <div>
              <span className="kind">{KIND[n.kind] || n.kind}</span>
              <strong>{n.title}</strong>
              {n.body && <p className="small">{n.body}</p>}
            </div>
            <span className="tiny muted">{fmtDate(n.created_at, true)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
