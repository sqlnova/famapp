"""Logistics Agent – proactive travel-time alerts + on-demand queries."""
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from agents.logistics.maps_client import get_travel_time
from agents.logistics.proactive import start_scheduler, stop_scheduler
from core.supabase_client import get_known_places_dict, resolve_place_address

logger = structlog.get_logger(__name__)


async def handle_logistics_query(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """On-demand logistics query from Intake Agent.

    Entities expected: { destination, event_time (optional), origin (optional) }
    """
    raw_destination = entities.get("destination")
    if not raw_destination:
        return "¿A dónde necesitás ir? Decime la dirección o el nombre del lugar."

    # Resolve alias ("colegio", "club") → full address
    try:
        known_places = get_known_places_dict()
        destination = resolve_place_address(raw_destination, known_places)
    except Exception:
        destination = raw_destination

    display_name = raw_destination  # keep original alias for the reply
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


__all__ = ["handle_logistics_query", "start_scheduler", "stop_scheduler"]
