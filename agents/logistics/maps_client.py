"""Google Maps Directions client – travel time with real traffic."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import googlemaps
import structlog

from core.config import get_settings

logger = structlog.get_logger(__name__)

_client: Optional[googlemaps.Client] = None

# Caché TTL: el mismo endpoint (/api/events, /api/routines, /api/plan)
# pide duración para los mismos (origen, destino, hora aprox) múltiples
# veces por render. El tráfico no cambia significativamente en 10 min,
# y las llamadas a Maps son el cuello más caro (latencia red + billing).
_TRAVEL_CACHE_TTL = 600.0
_TRAVEL_BUCKET_SECONDS = 600  # redondeo de departure_time a 10 minutos
_travel_cache: dict[tuple, tuple[float, "TravelInfo"]] = {}
_travel_cache_lock = threading.Lock()


def _get_maps() -> googlemaps.Client:
    global _client
    if _client is None:
        s = get_settings()
        if not s.google_maps_api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is not set")
        _client = googlemaps.Client(key=s.google_maps_api_key)
    return _client


def _travel_cache_get(key: tuple) -> Optional["TravelInfo"]:
    with _travel_cache_lock:
        entry = _travel_cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            _travel_cache.pop(key, None)
            return None
        return value


def _travel_cache_set(key: tuple, value: "TravelInfo") -> None:
    with _travel_cache_lock:
        _travel_cache[key] = (time.monotonic() + _TRAVEL_CACHE_TTL, value)


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
    origin = origin or s.home_address
    departure_time = departure_time or datetime.now(timezone.utc)

    # Redondeamos al bucket de 10 min para maximizar hits entre llamadas
    # que piden rutas para horarios cercanos (mismo evento visto desde
    # distintos endpoints en un render del Home).
    bucket = int(departure_time.timestamp()) // _TRAVEL_BUCKET_SECONDS
    cache_key = (origin, destination, bucket)
    cached = _travel_cache_get(cache_key)
    if cached is not None:
        return cached

    maps = _get_maps()
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
    _travel_cache_set(cache_key, info)
    return info
