"""Logistics Agent – proactive travel-time alerts.

Status: STUB – to be implemented in next iteration.

Responsibilities:
- Poll Google Calendar for upcoming events with a location
- Calculate real travel time using Google Maps Directions API (with traffic)
- Schedule a proactive WhatsApp push "Salí en X minutos" to relevant family members
- Store and manage pending alerts in logistics_alerts table
- Cancel/update alerts if calendar changes
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


async def handle_logistics_query(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """Entry point for on-demand logistics queries from Intake Agent.

    Args:
        sender: WhatsApp number of the requester.
        entities: { destination, event_time, origin }
        message_sid: Original message SID.

    Returns:
        Response text with estimated travel info.
    """
    logger.info("logistics_agent_called", sender=sender, entities=entities)
    destination = entities.get("destination", "tu destino")
    # TODO: call Google Maps Directions API with departure_time=now+buffer
    return (
        f"Calculando tiempo de viaje a '{destination}'… "
        "(Integración con Google Maps próximamente)"
    )


async def schedule_proactive_alerts() -> None:
    """Cron job: check calendar events in next 3h and schedule departure alerts.

    Called periodically by the scheduler (e.g. APScheduler or Supabase cron).
    """
    logger.info("logistics_proactive_check_started")
    # TODO:
    # 1. Fetch calendar events in next 3 hours that have a location
    # 2. For each event, call Maps API to get travel time from home
    # 3. Calculate send_at = event.start - travel_time - 10min buffer
    # 4. If send_at > now and no alert exists, insert into logistics_alerts
    # 5. A separate process polls logistics_alerts and fires WhatsApp messages
