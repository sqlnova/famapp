/**
 * Minimalist isometric "office" visualization.
 *
 * One SVG, no CSS rotate hacks. Four workstations laid out on a subtle
 * isometric grid. Each workstation is a small desk + monitor whose
 * screen and surrounding glow reflect the agent's current status.
 *
 * Projection: classic 2:1 isometric where
 *   screenX = (x - y) * (TILE_W / 2)
 *   screenY = (x + y) * (TILE_H / 2) - z
 */

const TILE_W = 120;
const TILE_H = 60;
const ORIGIN_X = 340;
const ORIGIN_Y = 90;

const iso = (x, y, z = 0) => ({
  x: ORIGIN_X + (x - y) * (TILE_W / 2),
  y: ORIGIN_Y + (x + y) * (TILE_H / 2) - z,
});

// 2x2 grid — front row (intake, schedule), back row (logistics, shopping).
// Positions picked so the furthest desks sit "higher" on screen.
const LAYOUT = {
  intake: { gx: 0, gy: 2 },
  schedule: { gx: 2, gy: 2 },
  logistics: { gx: 0, gy: 0 },
  shopping: { gx: 2, gy: 0 },
};

const STATUS_COLORS = {
  idle: {
    screen: "#2a2a33",
    screenEdge: "#3a3a45",
    glow: null,
    accent: "#6b7280",
  },
  active: {
    screen: "#10b981",
    screenEdge: "#34d399",
    glow: "rgba(16, 185, 129, 0.35)",
    accent: "#10b981",
  },
  error: {
    screen: "#ef4444",
    screenEdge: "#f87171",
    glow: "rgba(239, 68, 68, 0.40)",
    accent: "#ef4444",
  },
};

function polygonPoints(points) {
  return points.map((p) => `${p.x},${p.y}`).join(" ");
}

function FloorTile({ gx, gy }) {
  const a = iso(gx, gy);
  const b = iso(gx + 2, gy);
  const c = iso(gx + 2, gy + 2);
  const d = iso(gx, gy + 2);
  return (
    <polygon
      points={polygonPoints([a, b, c, d])}
      fill="url(#floor-gradient)"
      stroke="rgba(255,255,255,0.04)"
      strokeWidth="1"
    />
  );
}

function Workstation({ agent, position }) {
  const { gx, gy } = position;
  const colors = STATUS_COLORS[agent.status] || STATUS_COLORS.idle;

  // Desk footprint: 1.4 x 0.9 tiles, centered in the 2x2 floor slot.
  const dx = gx + 0.3;
  const dy = gy + 0.55;
  const dw = 1.4;
  const dh = 0.9;
  const deskH = 18;

  // Desk top (flat diamond)
  const topA = iso(dx, dy, deskH);
  const topB = iso(dx + dw, dy, deskH);
  const topC = iso(dx + dw, dy + dh, deskH);
  const topD = iso(dx, dy + dh, deskH);
  // Visible sides (front-right + front-left)
  const botB = iso(dx + dw, dy, 0);
  const botC = iso(dx + dw, dy + dh, 0);
  const botD = iso(dx, dy + dh, 0);

  // Monitor sits on back corner of desk (small box + screen)
  const mx = dx + 0.35;
  const my = dy + 0.15;
  const mw = 0.55;
  const md = 0.1;
  const mh = 28; // screen height above desk top

  const sA = iso(mx, my, deskH + mh);
  const sB = iso(mx + mw, my, deskH + mh);
  const sC = iso(mx + mw, my, deskH);
  const sD = iso(mx, my, deskH);
  // Monitor right side (depth)
  const sE = iso(mx + mw, my + md, deskH + mh);
  const sF = iso(mx + mw, my + md, deskH);

  // Label anchor (in front of desk)
  const label = iso(dx + dw / 2, dy + dh + 0.35, 0);

  const gId = `glow-${agent.key}`;

  return (
    <g className={`workstation ws-${agent.status}`}>
      {/* Status glow under the desk */}
      {colors.glow && (
        <ellipse
          cx={iso(dx + dw / 2, dy + dh / 2, 0).x}
          cy={iso(dx + dw / 2, dy + dh / 2, 0).y}
          rx={90}
          ry={42}
          fill={colors.glow}
          filter={`url(#${gId})`}
          className="ws-glow"
        />
      )}

      {/* Desk sides (darker) */}
      <polygon
        points={polygonPoints([topD, topC, botC, botD])}
        fill="#1c1c22"
      />
      <polygon
        points={polygonPoints([topC, topB, botB, botC])}
        fill="#141418"
      />
      {/* Desk top */}
      <polygon
        points={polygonPoints([topA, topB, topC, topD])}
        fill="#2a2a33"
        stroke={colors.accent}
        strokeWidth={agent.status === "idle" ? 0.5 : 1.5}
        opacity={agent.status === "idle" ? 0.9 : 1}
      />

      {/* Monitor depth */}
      <polygon
        points={polygonPoints([sB, sE, sF, sC])}
        fill="#0d0d12"
      />
      {/* Monitor screen */}
      <polygon
        points={polygonPoints([sA, sB, sC, sD])}
        fill={colors.screen}
        stroke={colors.screenEdge}
        strokeWidth="1"
        className="ws-screen"
      />

      {/* Label */}
      <text
        x={label.x}
        y={label.y + 14}
        textAnchor="middle"
        className="ws-label"
      >
        {agent.label}
      </text>
      <text
        x={label.x}
        y={label.y + 30}
        textAnchor="middle"
        className={`ws-status ws-status-${agent.status}`}
      >
        {agent.status}
      </text>
    </g>
  );
}

export default function IsometricOffice({ agents }) {
  return (
    <div className="iso-wrap">
      <svg
        viewBox="0 0 720 400"
        className="iso-svg"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="floor-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#17171d" />
            <stop offset="100%" stopColor="#0e0e12" />
          </linearGradient>
          <linearGradient id="bg-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0b0b10" />
            <stop offset="100%" stopColor="#07070a" />
          </linearGradient>
          {agents.map((a) => {
            const glow = STATUS_COLORS[a.status]?.glow;
            return (
              <filter
                key={a.key}
                id={`glow-${a.key}`}
                x="-50%"
                y="-50%"
                width="200%"
                height="200%"
              >
                <feGaussianBlur stdDeviation={glow ? 10 : 0} />
              </filter>
            );
          })}
        </defs>

        {/* Background */}
        <rect width="720" height="400" fill="url(#bg-gradient)" />

        {/* Floor tiles (2x2 each) */}
        {agents.map((a) => {
          const pos = LAYOUT[a.key];
          return <FloorTile key={`floor-${a.key}`} gx={pos.gx} gy={pos.gy} />;
        })}

        {/* Workstations — render back rows first so front occludes them */}
        {[...agents]
          .sort((a, b) => {
            const pa = LAYOUT[a.key];
            const pb = LAYOUT[b.key];
            return pa.gy + pa.gx - (pb.gy + pb.gx);
          })
          .reverse()
          .map((a) => (
            <Workstation key={a.key} agent={a} position={LAYOUT[a.key]} />
          ))}
      </svg>
    </div>
  );
}
