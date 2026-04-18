import { useMemo } from "react";
import useMonitoringSocket from "./hooks/useMonitoringSocket.js";
import Office from "./components/Office.jsx";
import EventFeed from "./components/EventFeed.jsx";
import StatusBadge from "./components/StatusBadge.jsx";

const WS_URL =
  import.meta.env.VITE_MONITORING_WS_URL || "ws://localhost:8001/ws";

const AGENTS = [
  { key: "intake", label: "Intake Agent" },
  { key: "schedule", label: "Schedule Agent" },
  { key: "logistics", label: "Logistics Agent" },
  { key: "shopping", label: "Shopping Agent" },
];

export default function App() {
  const { agents, events, connection } = useMonitoringSocket(WS_URL);

  const agentList = useMemo(
    () =>
      AGENTS.map((a) => {
        const live = agents[a.key];
        return {
          ...a,
          status: live?.status || "idle",
          message: live?.message || "",
          timestamp: live?.timestamp || null,
        };
      }),
    [agents],
  );

  return (
    <div className="app">
      <header className="app-header">
        <h1>FamApp • Agent Control Room</h1>
        <span className={`conn conn-${connection}`}>
          {connection === "open"
            ? "● live"
            : connection === "connecting"
              ? "… connecting"
              : "○ offline"}
        </span>
      </header>

      <main className="app-main">
        <section className="office-panel">
          <Office agents={agentList} />
          <div className="badge-row">
            {agentList.map((a) => (
              <StatusBadge key={a.key} agent={a} />
            ))}
          </div>
        </section>

        <aside className="feed-panel">
          <h2>Event Feed</h2>
          <EventFeed events={events} />
        </aside>
      </main>

      <footer className="app-footer">
        <span>WS: {WS_URL}</span>
      </footer>
    </div>
  );
}
