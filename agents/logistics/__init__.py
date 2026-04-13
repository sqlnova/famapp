"""Logistics Agent – proactive travel-time alerts + on-demand queries."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from agents.logistics.maps_client import get_travel_time
from agents.logistics.proactive import schedule_manual_alert, start_scheduler, stop_scheduler
from agents.schedule.calendar_client import AR_TZ, list_upcoming_events
from core.supabase_client import get_known_places_dict, resolve_place_address

logger = structlog.get_logger(__name__)


async def handle_logistics_query(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """On-demand logistics query from Intake Agent."""
    action = entities.get("action", "travel_time")

    if action == "request_alert":
        return await _handle_alert_request(
            event_name=entities.get("event_name", ""),
            date_str=entities.get("date") or "",
        )

    # ── travel_time ────────────────────────────────────────────────────────────
    raw_destination = entities.get("destination")
    if not raw_destination:
        return "¿A dónde necesitás ir? Decime la dirección o el nombre del lugar."

    # Resolve alias ("colegio", "club") → full address
    try:
        known_places = get_known_places_dict()
        destination = resolve_place_address(raw_destination, known_places)
    except Exception:
        destination = raw_destination

    display_name = raw_destination
    try:
        travel = get_travel_time(destination=destination)
        duration = travel.human_readable()
        dist = travel.distance_km
        return (
            f"🚗 Para ir a *{display_name}*:\n"
            f"⏱ Tiempo estimado: *{duration}* (con tráfico)\n"
            f"📏 Distancia: {dist} km\n"
            f"🛣 Ruta: {travel.summary}"
        )
    except ValueError:
        return f"No encontré ruta a '{display_name}'. ¿Podés ser más específica con la dirección?"
    except Exception:
        logger.exception("logistics_query_error", destination=destination)
        return "No pude calcular el tiempo de viaje ahora. Intentá de nuevo."


async def _handle_alert_request(event_name: str, date_str: str) -> str:
    """Find a calendar event by name (+ optional date) and schedule a departure alert."""
    if not event_name:
        return "¿Para qué evento querés la notificación? Decime el nombre o lugar."

    # Resolve alias → address for location-based matching
    try:
        known_places = get_known_places_dict()
    except Exception:
        known_places = {}

    place = known_places.get(event_name.lower().strip())
    place_address = place.address.lower() if place else None

    # Fetch upcoming events (14-day window)
    try:
        events = list_upcoming_events(days=14)
    except Exception:
        logger.exception("alert_request_calendar_error")
        return "No pude acceder al calendario ahora. Intentá de nuevo."

    # Parse target date
    target_date = None
    if date_str:
        try:
            target_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            pass

    search = event_name.lower().strip()

    def matches(event) -> bool:
        title_l = event.title.lower()
        location_l = (event.location or "").lower()
        name_hit = search in title_l or search in location_l
        place_hit = place_address and place_address in location_l
        return name_hit or place_hit

    matching = [e for e in events if matches(e)]

    # Apply date filter if provided
    if target_date:
        matching = [e for e in matching if e.start.astimezone(AR_TZ).date() == target_date]

    if not matching:
        date_hint = f" para el {date_str}" if date_str else ""
        return (
            f"No encontré ningún evento relacionado con '{event_name}'{date_hint} "
            f"en los próximos 14 días."
        )

    # If no date specified, take only the first (earliest) match
    if not target_date:
        matching = [matching[0]]

    results: List[str] = []
    for event in matching:
        results.append(await schedule_manual_alert(event))

    return "\n\n".join(results)


__all__ = ["handle_logistics_query", "start_scheduler", "stop_scheduler"]
