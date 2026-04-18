const AGENT_LABELS = {
  intake: "Intake",
  schedule: "Schedule",
  logistics: "Logistics",
  shopping: "Shopping",
};

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function EventFeed({ events }) {
  if (!events.length) {
    return <div className="feed-empty">Waiting for agent activity…</div>;
  }
  return (
    <ul className="feed-list">
      {events.map((e, i) => (
        <li key={`${e.timestamp}-${i}`} className={`feed-item feed-${e.status}`}>
          <span className="feed-time">{formatTime(e.timestamp)}</span>
          <span className={`feed-agent agent-tag-${e.agent_name}`}>
            {AGENT_LABELS[e.agent_name] || e.agent_name}
          </span>
          <span className={`feed-status status-${e.status}`}>{e.status}</span>
          <span className="feed-message">{e.message || "—"}</span>
        </li>
      ))}
    </ul>
  );
}
