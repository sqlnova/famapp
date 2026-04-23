# FamApp Agent Monitoring Dashboard

A React + Vite dashboard that shows FamApp's five LangGraph agents
(Intake, Schedule, Logistics, Shopping, Homework) in a pixel-art isometric
office, one desk per agent, with a live event feed.

Hosted separately on **Cloudflare Pages** (or any static host).
Connects to the monitoring backend via WebSocket.

## Local dev

```bash
cd dashboard
npm install
cp .env.example .env            # edit VITE_MONITORING_WS_URL if needed
npm run dev                     # http://localhost:5173
```

By default it connects to `ws://localhost:8001/ws`. Change via:

```bash
VITE_MONITORING_WS_URL=wss://famapp-monitoring.up.railway.app/ws
```

## Production build

```bash
npm run build        # outputs dashboard/dist/
npm run preview      # serves the built site locally
```

## Cloudflare Pages deployment

Option A — Pages dashboard (recommended):

1. Cloudflare Pages → **Create project → Connect to Git** → pick this repo.
2. **Build settings**:
   * **Framework preset:** Vite
   * **Build command:** `npm run build`
   * **Build output directory:** `dist`
   * **Root directory:** `dashboard`
3. **Environment variables:** add `VITE_MONITORING_WS_URL` pointing at your
   Railway service, e.g. `wss://famapp-monitoring.up.railway.app/ws`.
4. Deploy.

Option B — Wrangler:

```bash
cd dashboard
npm run build
npx wrangler pages deploy dist --project-name famapp-monitoring
```

## How it works

* `useMonitoringSocket` opens the WebSocket, applies the initial
  `snapshot` payload, then appends each incoming `event`. It
  reconnects with exponential backoff (max 15 s) on disconnect.
* `Office` renders a tilted (`rotateX/rotateZ`) tiled floor with five
  desk slots. Each `Desk` counter-rotates so sprites stay upright.
* `AgentSprite` is a small SVG pixel character. CSS classes driven by
  `status` add glow/bob (active) or shake/red tint (error).
* `EventFeed` shows the most recent 20 events.

No auth and no secrets in the frontend — this is an internal tool.
