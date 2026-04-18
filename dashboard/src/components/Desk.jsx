import AgentSprite from "./AgentSprite.jsx";

/**
 * A single pixel-art desk with a sitting agent sprite on top.
 * The surrounding CSS handles glow / error-indicator styling based on status.
 */
export default function Desk({ agent }) {
  return (
    <div className={`desk desk-${agent.status}`} data-agent={agent.key}>
      <div className="desk-nameplate">{agent.label}</div>

      <div className="desk-sprite-wrap">
        <AgentSprite agentKey={agent.key} status={agent.status} />
        {agent.status === "error" && <div className="error-indicator">!</div>}
        {agent.status === "active" && <div className="active-glow" />}
      </div>

      <svg
        className="desk-furniture"
        viewBox="0 0 160 90"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        {/* Isometric desk top */}
        <polygon points="20,50 80,20 140,50 80,80" fill="#8b5a2b" stroke="#4d2f17" strokeWidth="2" />
        <polygon points="20,50 80,80 80,84 20,54" fill="#4d2f17" />
        <polygon points="140,50 80,80 80,84 140,54" fill="#6b4422" />
        {/* Monitor */}
        <polygon points="70,35 90,35 90,50 70,50" fill="#1a1a1a" stroke="#000" strokeWidth="1.5" />
        <polygon points="72,37 88,37 88,48 72,48" fill="#0f4c3a" />
        {/* Monitor stand */}
        <polygon points="77,50 83,50 82,54 78,54" fill="#2a2a2a" />
        {/* Keyboard */}
        <polygon points="68,55 92,55 94,60 66,60" fill="#d0d0d0" stroke="#555" strokeWidth="1" />
      </svg>
    </div>
  );
}
