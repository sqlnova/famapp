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

const STATUS_LABEL = {
  idle: "Idle",
  active: "Active",
  error: "Error",
};

export default function AgentCard({ agent }) {
  return (
    <div className={`agent-card status-${agent.status}`}>
      <div className="agent-card-head">
        <div>
          <div className="agent-name">{agent.label}</div>
          <div className="agent-sub">{agent.description}</div>
        </div>
        <div className={`pill pill-${agent.status}`}>
          <span className="pill-dot" />
          {STATUS_LABEL[agent.status] || agent.status}
        </div>
      </div>
      <div className="agent-card-body">
        <div className="agent-message" title={agent.message || ""}>
          {agent.message || "No recent activity"}
        </div>
        <div className="agent-time mono">{formatTime(agent.timestamp)}</div>
      </div>
    </div>
  );
}
