/**
 * Pixel-art agent sprites rendered as SVG. Each agent has a distinct
 * color palette. Status maps to animation via CSS:
 *   - idle:   sitting still
 *   - active: subtle bob + glow (handled by parent .active-glow + CSS)
 *   - error:  red tint (handled by parent .desk-error CSS)
 */
const PALETTES = {
  intake: { shirt: "#3b82f6", hair: "#1f2937", skin: "#f4c28a" },
  schedule: { shirt: "#a855f7", hair: "#4b2e14", skin: "#f1b585" },
  logistics: { shirt: "#22c55e", hair: "#2c2c2c", skin: "#e9b487" },
  shopping: { shirt: "#f97316", hair: "#5a2e0a", skin: "#f4c28a" },
};

export default function AgentSprite({ agentKey, status }) {
  const p = PALETTES[agentKey] || PALETTES.intake;
  return (
    <svg
      className={`agent-sprite agent-${status}`}
      viewBox="0 0 32 40"
      shapeRendering="crispEdges"
      aria-label={`${agentKey} sprite`}
    >
      {/* hair */}
      <rect x="11" y="4" width="10" height="6" fill={p.hair} />
      <rect x="10" y="5" width="1" height="4" fill={p.hair} />
      <rect x="21" y="5" width="1" height="4" fill={p.hair} />
      {/* face */}
      <rect x="11" y="10" width="10" height="7" fill={p.skin} />
      {/* eyes */}
      <rect x="13" y="13" width="2" height="2" fill="#000" />
      <rect x="17" y="13" width="2" height="2" fill="#000" />
      {/* body / shirt */}
      <rect x="9" y="17" width="14" height="10" fill={p.shirt} />
      <rect x="9" y="17" width="14" height="2" fill="#fff" opacity="0.15" />
      {/* arms */}
      <rect x="6" y="19" width="3" height="7" fill={p.shirt} />
      <rect x="23" y="19" width="3" height="7" fill={p.shirt} />
      <rect x="6" y="26" width="3" height="2" fill={p.skin} />
      <rect x="23" y="26" width="3" height="2" fill={p.skin} />
      {/* chair back poking up */}
      <rect x="8" y="24" width="16" height="1" fill="#1f2937" opacity="0.3" />
    </svg>
  );
}
