import { useMemo } from "react";
import useMonitoringSocket from "./hooks/useMonitoringSocket.js";
import IsometricOffice from "./components/IsometricOffice.jsx";
import EventFeed from "./components/EventFeed.jsx";
import AgentCard from "./components/AgentCard.jsx";

const WS_URL =
  import.meta.env.VITE_MONITORING_WS_URL ||
  "wss://web-production-44587.up.railway.app/ws";

const AGENTS = [
  { key: "intake", label: "Intake", description: "Routing & classification" },
  { key: "schedule", label: "Schedule", description: "Calendar operations" },
  { key: "logistics", label: "Logistics", description: "Travel & alerts" },
  { key: "shopping", label: "Shopping", description: "Grocery list" },
  { key: "homework", label: "Homework", description: "School tasks & reminders" },
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

  const connLabel =
    connection === "open"
      ? "Live"
      : connection === "connecting"
        ? "Connecting"
        : "Offline";

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true" />
          <div>
            <div className="brand-title">FamApp</div>
            <div className="brand-subtitle">Agent Monitoring</div>
          </div>
        </div>
        <div className={`conn conn-${connection}`}>
          <span className="conn-dot" />
          {connLabel}
        </div>
      </header>

      <main className="app-main">
        <section className="left-col">
          <div className="panel panel-office">
            <div className="panel-header">
              <h2>Overview</h2>
              <span className="panel-hint">
                {agentList.filter((a) => a.status === "active").length} active
                · {agentList.filter((a) => a.status === "error").length} error
              </span>
            </div>
            <IsometricOffice agents={agentList} />
          </div>

          <div className="agent-grid">
            {agentList.map((a) => (
              <AgentCard key={a.key} agent={a} />
            ))}
          </div>
        </section>

        <aside className="panel panel-feed">
          <div className="panel-header">
            <h2>Event feed</h2>
            <span className="panel-hint">last 20</span>
          </div>
          <EventFeed events={events} />
        </aside>
      </main>

      <footer className="app-footer">
        <span className="mono">{WS_URL}</span>
      </footer>
    </div>
  );
}
