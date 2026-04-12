"""Schedule Agent – manages Google Calendar events.

Status: STUB – to be implemented in next iteration.

Responsibilities:
- Create / update / delete calendar events via Google Calendar API
- Query upcoming events for a time range
- Detect conflicts and suggest alternatives
- Notify family members of changes via WhatsApp
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


async def handle_schedule_request(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """Entry point called by Intake Agent when intent == 'schedule'.

    Args:
        sender: WhatsApp number of the requester.
        entities: Extracted entities from Intake (title, date, time, location, people).
        message_sid: Original message SID for traceability.

    Returns:
        Response text to send back to the user.
    """
    logger.info("schedule_agent_called", sender=sender, entities=entities)
    # TODO: implement Google Calendar integration
    title = entities.get("title", "evento")
    date = entities.get("date", "")
    time_ = entities.get("time", "")
    date_str = f" el {date}" if date else ""
    time_str = f" a las {time_}" if time_ else ""
    return f"Anotado: '{title}'{date_str}{time_str}. (Integración con Google Calendar próximamente)"
