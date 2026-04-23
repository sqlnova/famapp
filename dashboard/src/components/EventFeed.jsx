const AGENT_LABELS = {
  intake: "Intake",
  schedule: "Schedule",
  logistics: "Logistics",
  shopping: "Shopping",
  homework: "Homework",
};

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], {
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
        <li key={`${e.timestamp}-${i}`} className={`feed-row feed-${e.status}`}>
          <div className="feed-row-head">
            <span className={`feed-agent agent-${e.agent_name}`}>
              {AGENT_LABELS[e.agent_name] || e.agent_name}
            </span>
            <span className={`feed-status status-${e.status}`}>
              <span className="feed-status-dot" />
              {e.status}
            </span>
            <span className="feed-time mono">{formatTime(e.timestamp)}</span>
          </div>
          <div className="feed-message">{e.message || "—"}</div>
        </li>
      ))}
    </ul>
  );
}
