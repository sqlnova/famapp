function formatTime(iso) {
  if (!iso) return "—";
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

const LABELS = { idle: "Idle", active: "Active", error: "Error" };

export default function StatusBadge({ agent }) {
  return (
    <div className={`status-badge badge-${agent.status}`}>
      <div className="badge-name">{agent.label}</div>
      <div className="badge-status">{LABELS[agent.status] || agent.status}</div>
      <div className="badge-time">{formatTime(agent.timestamp)}</div>
    </div>
  );
}
