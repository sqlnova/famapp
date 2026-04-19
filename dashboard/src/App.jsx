import { useState, useEffect, useRef } from “react”;

const WS_URL = import.meta?.env?.VITE_MONITORING_WS_URL || “wss://web-production-44587.up.railway.app/ws”;

const AGENTS = [
{ id: “intake”, label: “Intake”, icon: “⬡”, description: “Message ingestion & routing” },
{ id: “schedule”, label: “Schedule”, icon: “◈”, description: “Calendar & time management” },
{ id: “logistics”, label: “Logistics”, icon: “◎”, description: “Delivery & task tracking” },
{ id: “shopping”, label: “Shopping”, icon: “◇”, description: “Purchase & inventory” },
];

const STATUS_CONFIG = {
idle:    { color: “#334155”, glow: “none”, pulse: false, label: “IDLE” },
active:  { color: “#0ea5e9”, glow: “0 0 20px #0ea5e966, 0 0 60px #0ea5e922”, pulse: true, label: “ACTIVE” },
working: { color: “#f59e0b”, glow: “0 0 20px #f59e0b66, 0 0 60px #f59e0b22”, pulse: true, label: “WORKING” },
error:   { color: “#ef4444”, glow: “0 0 20px #ef444466”, pulse: false, label: “ERROR” },
done:    { color: “#10b981”, glow: “0 0 20px #10b98166”, pulse: false, label: “DONE” },
};

function useWebSocket(url) {
const [connected, setConnected] = useState(false);
const [events, setEvents] = useState([]);
const [agentStates, setAgentStates] = useState({
intake: { status: “idle”, message: “Waiting…” },
schedule: { status: “idle”, message: “Waiting…” },
logistics: { status: “idle”, message: “Waiting…” },
shopping: { status: “idle”, message: “Waiting…” },
});
const ws = useRef(null);
const reconnectTimer = useRef(null);

const connect = () => {
try {
ws.current = new WebSocket(url);
ws.current.onopen = () => setConnected(true);
ws.current.onclose = () => {
setConnected(false);
reconnectTimer.current = setTimeout(connect, 3000);
};
ws.current.onerror = () => ws.current?.close();
ws.current.onmessage = (e) => {
try {
const data = JSON.parse(e.data);
if (data.agent_name) {
setAgentStates(prev => ({
…prev,
[data.agent_name]: { status: data.status || “active”, message: data.message || “” },
}));
setEvents(prev => [{
id: Date.now(),
agent: data.agent_name,
status: data.status,
message: data.message,
ts: new Date().toLocaleTimeString(“en-US”, { hour12: false }),
}, …prev].slice(0, 50));
}
} catch {}
};
} catch {}
};

useEffect(() => {
connect();
return () => {
clearTimeout(reconnectTimer.current);
ws.current?.close();
};
}, []);

return { connected, agentStates, events };
}

function AgentCard({ agent, state }) {
const cfg = STATUS_CONFIG[state.status] || STATUS_CONFIG.idle;
const isActive = cfg.pulse;

return (
<div style={{
background: “linear-gradient(135deg, #0f172a 0%, #0c1322 100%)”,
border: `1px solid ${isActive ? cfg.color + "44" : "#1e293b"}`,
borderRadius: 2,
padding: “1.5rem”,
position: “relative”,
overflow: “hidden”,
transition: “all 0.4s ease”,
boxShadow: isActive ? cfg.glow : “none”,
}}>
{/* Corner accent */}
<div style={{
position: “absolute”, top: 0, right: 0,
width: 40, height: 40,
borderTop: `2px solid ${cfg.color}`,
borderRight: `2px solid ${cfg.color}`,
opacity: isActive ? 1 : 0.2,
transition: “opacity 0.4s”,
}} />
<div style={{
position: “absolute”, bottom: 0, left: 0,
width: 20, height: 20,
borderBottom: `1px solid ${cfg.color}`,
borderLeft: `1px solid ${cfg.color}`,
opacity: isActive ? 0.6 : 0.1,
transition: “opacity 0.4s”,
}} />

```
  {/* Scan line animation when active */}
  {isActive && (
    <div style={{
      position: "absolute", top: 0, left: 0, right: 0,
      height: "100%",
      background: `linear-gradient(180deg, transparent 0%, ${cfg.color}08 50%, transparent 100%)`,
      animation: "scan 2s ease-in-out infinite",
      pointerEvents: "none",
    }} />
  )}

  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
    <div>
      <div style={{
        fontSize: 11, letterSpacing: 4, color: "#475569",
        fontFamily: "'DM Mono', 'Fira Code', monospace",
        marginBottom: 6,
      }}>
        AGENT
      </div>
      <div style={{
        fontSize: 20, fontWeight: 600, color: "#f1f5f9",
        fontFamily: "'Outfit', 'DM Sans', sans-serif",
        letterSpacing: 1,
      }}>
        {agent.label}
      </div>
    </div>
    <div style={{
      fontSize: 28, color: cfg.color,
      opacity: isActive ? 1 : 0.3,
      transition: "all 0.4s",
      filter: isActive ? `drop-shadow(0 0 8px ${cfg.color})` : "none",
    }}>
      {agent.icon}
    </div>
  </div>

  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
    <div style={{
      width: 6, height: 6, borderRadius: "50%",
      background: cfg.color,
      boxShadow: isActive ? `0 0 8px ${cfg.color}` : "none",
      animation: cfg.pulse ? "blink 1.4s ease-in-out infinite" : "none",
      flexShrink: 0,
    }} />
    <span style={{
      fontSize: 10, letterSpacing: 3,
      color: cfg.color,
      fontFamily: "'DM Mono', monospace",
    }}>
      {cfg.label}
    </span>
  </div>

  <div style={{
    fontSize: 12, color: "#64748b",
    fontFamily: "'DM Mono', monospace",
    lineHeight: 1.5,
    minHeight: 36,
    overflow: "hidden",
    textOverflow: "ellipsis",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
  }}>
    {state.message || agent.description}
  </div>
</div>
```

);
}

function EventRow({ event, index }) {
const cfg = STATUS_CONFIG[event.status] || STATUS_CONFIG.idle;
return (
<div style={{
display: “grid”,
gridTemplateColumns: “60px 80px 1fr”,
gap: “0.75rem”,
padding: “0.6rem 0”,
borderBottom: “1px solid #0f172a”,
fontSize: 11,
fontFamily: “‘DM Mono’, monospace”,
animation: index === 0 ? “fadeIn 0.3s ease” : “none”,
opacity: 1 - (index * 0.03),
}}>
<span style={{ color: “#334155” }}>{event.ts}</span>
<span style={{ color: cfg.color, letterSpacing: 1 }}>{event.agent?.toUpperCase()}</span>
<span style={{ color: “#64748b”, overflow: “hidden”, textOverflow: “ellipsis”, whiteSpace: “nowrap” }}>
{event.message}
</span>
</div>
);
}

export default function Dashboard() {
const { connected, agentStates, events } = useWebSocket(WS_URL);
const [time, setTime] = useState(new Date());

useEffect(() => {
const t = setInterval(() => setTime(new Date()), 1000);
return () => clearInterval(t);
}, []);

const activeCount = Object.values(agentStates).filter(s => s.status !== “idle”).length;

return (
<div style={{
minHeight: “100vh”,
background: “#060b14”,
color: “#e2e8f0”,
fontFamily: “‘Outfit’, ‘DM Sans’, system-ui, sans-serif”,
padding: “1.5rem”,
boxSizing: “border-box”,
}}>
<style>{`@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=DM+Mono:wght@300;400;500&display=swap'); @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} } @keyframes scan { 0%{transform:translateY(-100%)} 100%{transform:translateY(100%)} } @keyframes fadeIn { from{opacity:0;transform:translateY(-4px)} to{opacity:1;transform:translateY(0)} } @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} } * { box-sizing: border-box; } ::-webkit-scrollbar { width: 3px } ::-webkit-scrollbar-track { background: transparent } ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px }`}</style>

```
  {/* Header */}
  <header style={{
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "2rem",
    paddingBottom: "1rem",
    borderBottom: "1px solid #0f172a",
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
      <div style={{
        width: 32, height: 32,
        border: "1.5px solid #0ea5e9",
        borderRadius: 2,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, color: "#0ea5e9",
        boxShadow: "0 0 12px #0ea5e944",
      }}>⬡</div>
      <div>
        <div style={{
          fontSize: 16, fontWeight: 600, letterSpacing: 2,
          color: "#f1f5f9",
        }}>
          FAMAPP
        </div>
        <div style={{
          fontSize: 10, letterSpacing: 4, color: "#334155",
          fontFamily: "'DM Mono', monospace",
        }}>
          AGENT CONTROL
        </div>
      </div>
    </div>

    <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
      {/* Active count */}
      <div style={{ textAlign: "right" }}>
        <div style={{
          fontSize: 28, fontWeight: 300, color: "#0ea5e9",
          lineHeight: 1, fontFamily: "'Outfit', sans-serif",
        }}>
          {activeCount}
        </div>
        <div style={{ fontSize: 9, letterSpacing: 3, color: "#334155", fontFamily: "'DM Mono', monospace" }}>
          ACTIVE
        </div>
      </div>

      {/* Live indicator */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "6px 12px",
        border: `1px solid ${connected ? "#10b98144" : "#ef444433"}`,
        borderRadius: 2,
        background: connected ? "#10b98108" : "#ef444408",
      }}>
        <div style={{
          width: 5, height: 5, borderRadius: "50%",
          background: connected ? "#10b981" : "#ef4444",
          boxShadow: connected ? "0 0 8px #10b981" : "none",
          animation: connected ? "blink 2s ease-in-out infinite" : "none",
        }} />
        <span style={{
          fontSize: 9, letterSpacing: 3,
          color: connected ? "#10b981" : "#ef4444",
          fontFamily: "'DM Mono', monospace",
        }}>
          {connected ? "LIVE" : "OFFLINE"}
        </span>
      </div>

      {/* Clock */}
      <div style={{
        fontSize: 12, letterSpacing: 2,
        color: "#334155",
        fontFamily: "'DM Mono', monospace",
      }}>
        {time.toLocaleTimeString("en-US", { hour12: false })}
      </div>
    </div>
  </header>

  {/* Main grid */}
  <div style={{
    display: "grid",
    gridTemplateColumns: "1fr 280px",
    gap: "1.5rem",
    height: "calc(100vh - 140px)",
  }}>
    {/* Left: Agent grid */}
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* System bar */}
      <div style={{
        display: "flex", gap: "1rem",
        padding: "0.75rem 1rem",
        background: "#0a1020",
        border: "1px solid #0f172a",
        borderRadius: 2,
      }}>
        {["SYS", "NET", "MEM", "API"].map((label, i) => (
          <div key={label} style={{ display: "flex", items: "center", gap: 8 }}>
            <span style={{ fontSize: 9, letterSpacing: 3, color: "#334155", fontFamily: "'DM Mono', monospace" }}>{label}</span>
            <div style={{ width: 40, height: 3, background: "#1e293b", borderRadius: 1, overflow: "hidden", marginTop: 1 }}>
              <div style={{
                height: "100%",
                width: `${[72, 45, 88, 31][i]}%`,
                background: ["#0ea5e9", "#10b981", "#f59e0b", "#0ea5e9"][i],
                borderRadius: 1,
              }} />
            </div>
          </div>
        ))}
        <div style={{ marginLeft: "auto", fontSize: 9, letterSpacing: 2, color: "#1e293b", fontFamily: "'DM Mono', monospace" }}>
          sqlnova/famapp · main
        </div>
      </div>

      {/* Agent cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: "1rem",
        flex: 1,
      }}>
        {AGENTS.map(agent => (
          <AgentCard
            key={agent.id}
            agent={agent}
            state={agentStates[agent.id] || { status: "idle", message: "" }}
          />
        ))}
      </div>

      {/* Bottom bar */}
      <div style={{
        padding: "0.6rem 1rem",
        background: "#0a1020",
        border: "1px solid #0f172a",
        borderRadius: 2,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span style={{ fontSize: 9, letterSpacing: 3, color: "#1e293b", fontFamily: "'DM Mono', monospace" }}>
          RAILWAY · europe-west4
        </span>
        <span style={{ fontSize: 9, letterSpacing: 3, color: "#1e293b", fontFamily: "'DM Mono', monospace" }}>
          web-production-44587.up.railway.app
        </span>
        <span style={{ fontSize: 9, letterSpacing: 3, color: connected ? "#10b98144" : "#ef444444", fontFamily: "'DM Mono', monospace" }}>
          {connected ? "● CONNECTED" : "○ RECONNECTING"}
        </span>
      </div>
    </div>

    {/* Right: Event feed */}
    <div style={{
      background: "#0a1020",
      border: "1px solid #0f172a",
      borderRadius: 2,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{
        padding: "0.75rem 1rem",
        borderBottom: "1px solid #0f172a",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span style={{ fontSize: 9, letterSpacing: 4, color: "#334155", fontFamily: "'DM Mono', monospace" }}>
          EVENT LOG
        </span>
        <span style={{ fontSize: 9, color: "#1e293b", fontFamily: "'DM Mono', monospace" }}>
          {events.length}
        </span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "0 1rem" }}>
        {events.length === 0 ? (
          <div style={{
            padding: "2rem 0",
            textAlign: "center",
            fontSize: 10,
            letterSpacing: 2,
            color: "#1e293b",
            fontFamily: "'DM Mono', monospace",
          }}>
            NO EVENTS
          </div>
        ) : (
          events.map((event, i) => <EventRow key={event.id} event={event} index={i} />)
        )}
      </div>

      {/* Feed footer */}
      <div style={{
        padding: "0.6rem 1rem",
        borderTop: "1px solid #0f172a",
        fontSize: 9,
        letterSpacing: 2,
        color: "#1e293b",
        fontFamily: "'DM Mono', monospace",
      }}>
        LAST 50 EVENTS
      </div>
    </div>
  </div>
</div>
```

);
}