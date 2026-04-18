# FamApp Agent Monitoring Backend

Standalone FastAPI service that tracks FamApp's LangGraph agents in
real time. Deploy as a **new Railway service** in the existing FamApp
Railway project.

## Endpoints

| Method | Path      | Purpose                                                    |
| ------ | --------- | ---------------------------------------------------------- |
| GET    | `/health` | Liveness probe.                                            |
| GET    | `/state`  | Full snapshot (`{ agents, events }`) — for HTTP bootstrap. |
| POST   | `/event`  | Ingest an agent event from the LangGraph runtime.          |
| WS     | `/ws`     | Live stream of events; sends `snapshot` on connect.        |

### Event schema

```json
{
  "agent_name": "intake",
  "status": "active",
  "message": "Classifying intent",
  "timestamp": "2026-04-18T14:22:05+00:00"
}
```

* `agent_name`: `intake | schedule | logistics | shopping`
* `status`: `idle | active | error`
* `timestamp`: optional — server fills it in when missing.

## Local dev

```bash
cd monitoring
pip install -r requirements.txt
uvicorn monitoring.app:app --reload --port 8001
```

Point the dashboard at `ws://localhost:8001/ws`
and LangGraph at `FAMAPP_MONITORING_URL=http://localhost:8001`.

## Railway deployment

1. In the existing FamApp Railway project, click **New → Service → GitHub repo**
   and pick this repo.
2. Under **Settings → Root Directory** set `monitoring`.
3. Railway's Nixpacks builder will pick up `requirements.txt` and use the
   `Procfile` start command, which binds to `$PORT` (Railway injects it).
4. Under **Networking**, enable a public HTTPS domain — the dashboard
   will connect at `wss://<your-service>.railway.app/ws`.

No environment variables are required (no auth, no DB).

## Design notes

* **In-memory only.** The event log is a `deque(maxlen=200)` — intentionally
  ephemeral. No durability needed for a live dashboard.
* **No auth.** Internal tool; protect via Railway's private networking or
  a Cloudflare Access policy if you need to lock it down.
* **Broadcast fan-out** is simple and tolerates dead sockets — failed sends
  are pruned from the connection set.
