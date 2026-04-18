import Desk from "./Desk.jsx";

/**
 * Isometric office view. Four desks in a 2x2 arrangement on a tiled floor.
 * Pure CSS/SVG — no game engine.
 */
export default function Office({ agents }) {
  return (
    <div className="office">
      <div className="office-floor">
        <div className="office-grid">
          {agents.map((agent, idx) => (
            <div className={`desk-slot slot-${idx}`} key={agent.key}>
              <Desk agent={agent} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
