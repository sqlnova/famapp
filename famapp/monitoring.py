"""Lightweight client for the FamApp Agent Monitoring backend.

Usage from a LangGraph node:

    from famapp.monitoring import send_event, track_node

    async def parse_and_classify(state):
        await send_event("intake", "active", "Classifying intent")
        try:
            result = await do_work(state)
        except Exception as exc:
            await send_event("intake", "error", f"parse failed: {exc}")
            raise
        await send_event("intake", "idle", "Classification done")
        return result

Or, using the context-manager helper which emits active→idle (or error)
automatically around a block:

    async def parse_and_classify(state):
        async with track_node("intake", "parse_and_classify"):
            return await do_work(state)

Configuration (all optional):
  FAMAPP_MONITORING_URL   Base URL of the monitoring service
                          (default: http://localhost:8001).
  FAMAPP_MONITORING_ENABLED
                          "0" / "false" disables event emission entirely —
                          safe to leave disabled in unit tests.
  FAMAPP_MONITORING_TIMEOUT
                          Per-request timeout in seconds (default: 2.0).

Emission failures are swallowed and logged. Monitoring must never break
the agent's real work.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset({"idle", "active", "error"})


def _enabled() -> bool:
    flag = os.environ.get("FAMAPP_MONITORING_ENABLED", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _base_url() -> str:
    return os.environ.get("FAMAPP_MONITORING_URL", "http://localhost:8001").rstrip("/")


def _timeout() -> float:
    try:
        return float(os.environ.get("FAMAPP_MONITORING_TIMEOUT", "2.0"))
    except ValueError:
        return 2.0


async def send_event(agent_name: str, status: str, message: str = "") -> None:
    """POST an event to the monitoring service. Never raises."""
    if not _enabled():
        return
    if status not in _VALID_STATUSES:
        logger.warning("monitoring_invalid_status status=%s", status)
        return

    payload = {
        "agent_name": agent_name,
        "status": status,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    url = f"{_base_url()}/event"
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        # Monitoring is best-effort; never break the agent.
        logger.debug("monitoring_send_failed url=%s err=%s", url, exc)


@asynccontextmanager
async def track_node(
    agent_name: str,
    node_name: Optional[str] = None,
) -> AsyncIterator[None]:
    """Emit active → idle (or error) around a LangGraph node body.

    ``node_name`` is included in the human-readable message so dashboards
    can show which step of the agent is running.
    """
    label = node_name or "running"
    await send_event(agent_name, "active", f"{label} started")
    try:
        yield
    except Exception as exc:
        await send_event(agent_name, "error", f"{label} failed: {exc}")
        raise
    else:
        await send_event(agent_name, "idle", f"{label} finished")
