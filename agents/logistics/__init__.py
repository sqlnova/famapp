"""Logistics Agent – proactive travel-time alerts + on-demand queries."""
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from agents.logistics.maps_client import get_travel_time
from agents.logistics.proactive import start_scheduler, stop_scheduler

logger = structlog.get_logger(__name__)


async def handle_logistics_query(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """On-demand logistics query from Intake Agent.

    Entities expected: { destination, event_time (optional), origin (optional) }
    """
    destination = entities.get("destination")
    if not destination:
        return "¿A dónde necesitás ir? Decime la dirección o el nombre del lugar."

    try:
        travel = get_travel_time(destination=destination)
        duration = travel.human_readable()
        dist = travel.distance_km

        return (
            f"🚗 Para ir a *{destination}*:\n"
            f"⏱ Tiempo estimado: *{duration}* (con tráfico)\n"
            f"📏 Distancia: {dist} km\n"
            f"🛣 Ruta: {travel.summary}"
        )
    except ValueError as e:
        return f"No encontré ruta a '{destination}'. ¿Podés ser más específica con la dirección?"
    except Exception:
        logger.exception("logistics_query_error", destination=destination)
        return "No pude calcular el tiempo de viaje ahora. Intentá de nuevo."


__all__ = ["handle_logistics_query", "start_scheduler", "stop_scheduler"]
