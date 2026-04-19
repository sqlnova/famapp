"""FamApp Agent Monitoring backend.

A standalone FastAPI service that:
  * Receives agent lifecycle events from LangGraph nodes via POST /event
  * Tracks per-agent status (idle / active / error) in memory
  * Broadcasts events and status snapshots to connected dashboards via
    the WebSocket at /ws
  * Keeps the last 200 events in an in-memory ring buffer

Intended to be deployed as a separate Railway service on port 8001.
No authentication — internal tool only.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger("famapp.monitoring")
logging.basicConfig(level=logging.INFO)

KNOWN_AGENTS: List[str] = [
    "intake",
    "schedule",
    "logistics",
    "shopping",
]
VALID_STATUSES: Set[str] = {"idle", "active", "error"}
MAX_EVENTS = 200


class AgentEvent(BaseModel):
    agent_name: str = Field(..., description="Canonical agent identifier, e.g. 'intake'")
    status: str = Field(..., description="One of idle|active|error")
    message: str = Field("", description="Human-readable description of what happened")
    timestamp: Optional[str] = Field(
        None,
        description="ISO-8601 UTC timestamp; filled server-side if omitted",
    )


class EventStore:
    """In-memory ring buffer + per-agent status tracker."""

    def __init__(self) -> None:
        self.events: Deque[dict] = deque(maxlen=MAX_EVENTS)
        self.agents: Dict[str, dict] = {
            name: {
                "agent_name": name,
                "status": "idle",
                "message": "",
                "timestamp": _utcnow_iso(),
            }
            for name in KNOWN_AGENTS
        }

    def record(self, event: AgentEvent) -> dict:
        if event.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{event.status}'")

        payload = {
            "agent_name": event.agent_name,
            "status": event.status,
            "message": event.message,
            "timestamp": event.timestamp or _utcnow_iso(),
        }
        self.events.append(payload)
        self.agents[event.agent_name] = dict(payload)
        return payload

    def snapshot(self) -> dict:
        return {
            "agents": list(self.agents.values()),
            "events": list(self.events),
        }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConnectionManager:
    """Tracks connected dashboard WebSockets and broadcasts JSON payloads."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws_connected total=%d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("ws_disconnected total=%d", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        dead: List[WebSocket] = []
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)


store = EventStore()
manager = ConnectionManager()

app = FastAPI(title="FamApp Agent Monitoring", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "agents": len(store.agents), "events": len(store.events)}


@app.get("/state")
async def state() -> dict:
    """Full snapshot — useful for dashboards that bootstrap over HTTP."""
    return store.snapshot()


@app.post("/event")
async def post_event(event: AgentEvent) -> dict:
    try:
        recorded = store.record(event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await manager.broadcast({"type": "event", "event": recorded})
    return {"ok": True, "event": recorded}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        # Bootstrap newly connected clients with the current snapshot.
        await ws.send_json({"type": "snapshot", **store.snapshot()})
        while True:
            # We don't expect inbound messages; keep the connection alive
            # and discard anything received.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_error")
    finally:
        await manager.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("monitoring.app:app", host="0.0.0.0", port=port, reload=False)
