"""Google Maps Directions client – travel time with real traffic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import googlemaps
import structlog

from core.config import get_settings

logger = structlog.get_logger(__name__)

_client: Optional[googlemaps.Client] = None


def _get_maps() -> googlemaps.Client:
    global _client
    if _client is None:
        s = get_settings()
        if not s.google_maps_api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is not set")
        _client = googlemaps.Client(key=s.google_maps_api_key)
    return _client


@dataclass
class TravelInfo:
    origin: str
    destination: str
    duration_seconds: int
    duration_in_traffic_seconds: int
    distance_meters: int
    summary: str  # route description

    @property
    def duration_minutes(self) -> int:
        return self.duration_in_traffic_seconds // 60

    @property
    def distance_km(self) -> float:
        return round(self.distance_meters / 1000, 1)

    def human_readable(self) -> str:
        mins = self.duration_minutes
        if mins < 60:
            return f"{mins} min"
        h, m = divmod(mins, 60)
        return f"{h}h {m}min" if m else f"{h}h"


def get_travel_time(
    destination: str,
    departure_time: Optional[datetime] = None,
    origin: Optional[str] = None,
) -> TravelInfo:
    """Calculate travel time from origin to destination with live traffic.

    Args:
        destination: Address or place name.
        departure_time: When to leave. Defaults to now.
        origin: Override the home address from config.
    """
    s = get_settings()
    maps = _get_maps()
    origin = origin or s.home_address
    departure_time = departure_time or datetime.now(timezone.utc)

    logger.info("maps_request", origin=origin, destination=destination)

    result = maps.directions(
        origin=origin,
        destination=destination,
        mode="driving",
        departure_time=departure_time,
        traffic_model="best_guess",
    )

    if not result:
        raise ValueError(f"No route found from '{origin}' to '{destination}'")

    leg = result[0]["legs"][0]
    duration_traffic = leg.get("duration_in_traffic", leg["duration"])

    info = TravelInfo(
        origin=origin,
        destination=destination,
        duration_seconds=leg["duration"]["value"],
        duration_in_traffic_seconds=duration_traffic["value"],
        distance_meters=leg["distance"]["value"],
        summary=result[0].get("summary", ""),
    )

    logger.info(
        "maps_result",
        destination=destination,
        duration_minutes=info.duration_minutes,
        distance_km=info.distance_km,
    )
    return info
