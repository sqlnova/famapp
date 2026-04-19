"""Expansión de rutinas semanales a eventos virtuales del día.

Una `FamilyRoutine` (p.ej. "Colegio de lunes a viernes 7:45 → 13:00")
describe un patrón recurrente. Para planificar un día concreto el pipeline
necesita eventos puntuales; este módulo materializa la rutina en uno o dos
`CalendarEvent` virtuales (ida + vuelta) para la fecha solicitada.

Principios:
- Sin efectos colaterales: genera nuevos `CalendarEvent`, no toca la rutina.
- Tolerante: si `outbound_time` o `return_time` faltan, simplemente no se
  genera ese extremo. Si ambos faltan, la rutina se descarta.
- Respeta excepciones (`RoutineException`) por fecha.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, time
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo

from core.models import (
    CalendarEvent,
    FamilyRoutine,
    KnownPlace,
    RoutineException,
)

# Mapa BYDAY iCal → weekday() de Python (lunes=0 … domingo=6)
_DAY_CODE_TO_WEEKDAY = {
    "MO": 0, "TU": 1, "WE": 2, "TH": 3,
    "FR": 4, "SA": 5, "SU": 6,
}

AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# Duración por defecto de cada extremo de la rutina cuando sólo hay hora
# de inicio — el bloque de logística casi siempre es un traslado corto.
_DEFAULT_DURATION_MIN = 15


def _parse_hhmm(value: Optional[str]) -> Optional[time]:
    """Aceptar 'HH:MM' o 'HH:MM:SS'; devolver None si es inválido."""
    if not value:
        return None
    try:
        parts = value.split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        return time(hour=hh, minute=mm)
    except (ValueError, IndexError):
        return None


def _routine_matches_weekday(routine: FamilyRoutine, target_weekday: int) -> bool:
    codes = routine.days or []
    for code in codes:
        wd = _DAY_CODE_TO_WEEKDAY.get(code.upper())
        if wd is not None and wd == target_weekday:
            return True
    return False


def _find_exception(
    routine: FamilyRoutine,
    date_iso: str,
    exceptions: Iterable[RoutineException],
) -> Optional[RoutineException]:
    if routine.id is None:
        return None
    for exc in exceptions:
        if exc.routine_id == routine.id and exc.date == date_iso:
            return exc
    return None


def _resolve_location(
    routine: FamilyRoutine,
    known_places: Iterable[KnownPlace],
) -> Optional[str]:
    """Devolver un string de ubicación útil para normalize.resolve_place."""
    if routine.place_alias:
        return routine.place_alias
    if routine.place_name:
        return routine.place_name
    # Si hay alias que matchea la rutina por título, lo usamos.
    title_lower = (routine.title or "").lower()
    for place in known_places:
        if place.alias and place.alias.lower() in title_lower:
            return place.alias
    return None


def _make_event(
    *,
    routine: FamilyRoutine,
    date_iso: str,
    t: time,
    kind_hint: str,  # "outbound" | "return"
    responsible: Optional[str],
    location: Optional[str],
) -> CalendarEvent:
    target_date = date_cls.fromisoformat(date_iso)
    start = datetime.combine(target_date, t, tzinfo=AR_TZ)
    end = start.replace() + _duration()

    verb = "Llevar" if kind_hint == "outbound" else "Retirar"
    kids = routine.children or []
    children_str = ", ".join(kids) if kids else ""
    place = location or ""
    # Título en español tipo "Llevar a Giuseppe, Isabella al colegio"
    pieces = [verb]
    if children_str:
        pieces.append(f"a {children_str}")
    if place:
        connector = "al" if kind_hint == "outbound" else "del"
        pieces.append(f"{connector} {place}")
    title = " ".join(pieces) if pieces else routine.title

    rid = str(routine.id) if routine.id else routine.title.replace(" ", "_")
    event_id = f"routine:{rid}:{date_iso}:{kind_hint}"

    return CalendarEvent(
        id=event_id,
        title=title,
        start=start,
        end=end,
        location=location,
        children=list(kids),
        responsible_nickname=responsible,
        alerts_enabled=False,  # rutinas no spamean alertas
    )


def _duration():
    from datetime import timedelta
    return timedelta(minutes=_DEFAULT_DURATION_MIN)


def expand_routines_for_day(
    routines: Iterable[FamilyRoutine],
    date_iso: str,
    known_places: Optional[Iterable[KnownPlace]] = None,
    exceptions: Optional[Iterable[RoutineException]] = None,
) -> List[CalendarEvent]:
    """Generar los `CalendarEvent` virtuales de todas las rutinas activas
    que aplican a la fecha dada.

    Args:
        routines: rutinas configuradas por la familia.
        date_iso: YYYY-MM-DD del día a planificar.
        known_places: opcional — para intentar inferir lugar desde el título.
        exceptions: excepciones puntuales (skip / override_responsible).

    Returns:
        Lista de `CalendarEvent` (ida y/o vuelta por cada rutina aplicable).
    """
    try:
        target = date_cls.fromisoformat(date_iso)
    except ValueError:
        return []

    target_weekday = target.weekday()
    places = list(known_places or [])
    excs = list(exceptions or [])

    events: List[CalendarEvent] = []
    for routine in routines:
        if not routine.is_active:
            continue
        if not _routine_matches_weekday(routine, target_weekday):
            continue

        exc = _find_exception(routine, date_iso, excs)
        if exc and exc.skip:
            continue

        override_responsible = exc.override_responsible if exc else None
        location = _resolve_location(routine, places)

        outbound_time = _parse_hhmm(routine.outbound_time)
        return_time = _parse_hhmm(routine.return_time)

        if outbound_time is not None:
            events.append(_make_event(
                routine=routine,
                date_iso=date_iso,
                t=outbound_time,
                kind_hint="outbound",
                responsible=override_responsible or routine.outbound_responsible,
                location=location,
            ))
        if return_time is not None:
            events.append(_make_event(
                routine=routine,
                date_iso=date_iso,
                t=return_time,
                kind_hint="return",
                responsible=override_responsible or routine.return_responsible,
                location=location,
            ))

    return events
