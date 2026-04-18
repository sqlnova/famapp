# FamApp Monitoring Dashboard — architecture

Three moving pieces:

```
┌──────────────────────────┐   POST /event         ┌────────────────────────┐
│ LangGraph agents         │ ───────────────────▶  │ Monitoring backend     │
│  (intake / schedule /    │                       │  FastAPI, Railway:8001 │
│   logistics / shopping)  │                       │  - in-mem ring buffer  │
│  famapp.monitoring       │                       │  - WS /ws broadcast    │
└──────────────────────────┘                       └─────────┬──────────────┘
                                                             │  ws:// snapshot
                                                             │       + events
                                                             ▼
                                               ┌────────────────────────┐
                                               │ React dashboard         │
                                               │  Cloudflare Pages       │
                                               │  Isometric pixel office │
                                               └────────────────────────┘
```

## 1. Event emission from LangGraph nodes

`famapp/monitoring.py` exposes two helpers:

```python
from famapp.monitoring import send_event, track_node

# Explicit form — full control over the message
await send_event("intake", "active", "Classifying intent")

# Context-manager form — auto active → idle, error on exception
async with track_node("schedule", "list_upcoming"):
    return await list_upcoming_events(days=7)
```

Both are no-ops if `FAMAPP_MONITORING_ENABLED=0` (handy for tests), and
network failures are swallowed so a monitoring outage can never break
the agent's real work.

### Where it's wired today

`agents/intake/nodes.py` (the fan-out hub) emits for all four agents:

* `parse_and_classify` → `intake` active/idle
* `handle_shopping` → `shopping` active / idle / error
* `handle_schedule` → `schedule` active / idle / error
* `handle_logistics` → `logistics` active / idle / error

`agents/intake/graph.py` emits `intake error` on an unhandled exception
in the graph.

Adding new hooks elsewhere is a one-liner — just `await send_event(...)`.

## 2. Monitoring backend (`monitoring/`)

Deployed as a **separate Railway service** inside the existing FamApp
project, root dir `monitoring/`, listening on `$PORT` (8001 locally).

State lives entirely in memory:

* `events`: `deque(maxlen=200)` — last N events.
* `agents`: `dict[name -> latest_event]` — current status per agent.

On a new WebSocket connection it sends a single `snapshot` frame with
both structures; subsequent `event` frames are pushed as they arrive.

## 3. Dashboard (`dashboard/`)

Hosted on Cloudflare Pages. The only runtime input is
`VITE_MONITORING_WS_URL`. The dashboard:

* Auto-reconnects with exponential backoff (1s → 15s cap).
* Shows four desks in an isometric office (CSS transforms + SVG sprites).
* Renders status via sprite animation:
  * idle → still
  * active → glow + bob
  * error → red tint + shake + `!` badge
* Live feed of the last 20 events with agent-colored tags.

## Environment variables

| Var                           | Where             | Purpose                                      |
| ----------------------------- | ----------------- | -------------------------------------------- |
| `FAMAPP_MONITORING_URL`       | main FamApp app   | Base URL of the monitoring service.          |
| `FAMAPP_MONITORING_ENABLED`   | main FamApp app   | Set `0` to silence emission (tests).         |
| `FAMAPP_MONITORING_TIMEOUT`   | main FamApp app   | HTTP timeout in seconds (default 2.0).       |
| `VITE_MONITORING_WS_URL`      | dashboard build   | `wss://…/ws` of the monitoring service.      |
| `PORT`                        | monitoring service| Provided by Railway.                         |
