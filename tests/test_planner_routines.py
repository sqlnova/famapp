"""Tests para core.planner.routines (expansión de rutinas → eventos)."""
from __future__ import annotations

from uuid import uuid4

from core.models import FamilyRoutine, KnownPlace, RoutineException
from core.planner.routines import expand_routines_for_day


# 2026-04-19 es domingo (weekday=6). 2026-04-20 es lunes (weekday=0).
# 2026-04-21 es martes (weekday=1).

def _colegio_routine(**overrides):
    base = dict(
        id=uuid4(),
        title="Colegio San Juan",
        days=["MO", "TU", "WE", "TH", "FR"],
        children=["Giuseppe", "Isabella"],
        outbound_time="07:45",
        return_time="13:00",
        outbound_responsible="papa",
        return_responsible="mama",
        place_alias="colegio",
        place_name="Colegio San Juan",
        is_active=True,
    )
    base.update(overrides)
    return FamilyRoutine(**base)


# ── Weekday matching ──────────────────────────────────────────────────────────

def test_expand_generates_outbound_and_return_on_matching_weekday():
    routine = _colegio_routine()
    events = expand_routines_for_day([routine], "2026-04-20")  # lunes
    assert len(events) == 2
    outbound, ret = sorted(events, key=lambda e: e.start)
    assert outbound.start.hour == 7 and outbound.start.minute == 45
    assert ret.start.hour == 13 and ret.start.minute == 0
    assert "Llevar" in outbound.title
    assert "Retirar" in ret.title
    assert outbound.responsible_nickname == "papa"
    assert ret.responsible_nickname == "mama"
    assert outbound.children == ["Giuseppe", "Isabella"]


def test_expand_skips_non_matching_weekday():
    routine = _colegio_routine()  # MO-FR
    events = expand_routines_for_day([routine], "2026-04-19")  # domingo
    assert events == []


def test_expand_skips_inactive_routine():
    routine = _colegio_routine(is_active=False)
    events = expand_routines_for_day([routine], "2026-04-20")
    assert events == []


# ── Partial times ─────────────────────────────────────────────────────────────

def test_expand_only_outbound_when_return_time_missing():
    routine = _colegio_routine(return_time=None)
    events = expand_routines_for_day([routine], "2026-04-20")
    assert len(events) == 1
    assert events[0].start.hour == 7


def test_expand_zero_events_when_no_times():
    routine = _colegio_routine(outbound_time=None, return_time=None)
    events = expand_routines_for_day([routine], "2026-04-20")
    assert events == []


def test_expand_tolerates_invalid_time_string():
    routine = _colegio_routine(outbound_time="no-es-hora", return_time="13:00")
    events = expand_routines_for_day([routine], "2026-04-20")
    assert len(events) == 1
    assert events[0].start.hour == 13


# ── Exceptions ────────────────────────────────────────────────────────────────

def test_expand_honors_skip_exception():
    routine = _colegio_routine()
    exc = RoutineException(
        routine_id=routine.id, date="2026-04-20", skip=True
    )
    events = expand_routines_for_day([routine], "2026-04-20", exceptions=[exc])
    assert events == []


def test_expand_exception_skip_only_applies_to_its_date():
    routine = _colegio_routine()
    exc = RoutineException(
        routine_id=routine.id, date="2026-04-20", skip=True
    )
    # Martes 21 no está alcanzado por la excepción del lunes 20 → se expande.
    events = expand_routines_for_day([routine], "2026-04-21", exceptions=[exc])
    assert len(events) == 2


def test_expand_override_responsible_applies():
    routine = _colegio_routine()
    exc = RoutineException(
        routine_id=routine.id,
        date="2026-04-20",
        skip=False,
        override_responsible="abuela",
    )
    events = expand_routines_for_day([routine], "2026-04-20", exceptions=[exc])
    assert all(e.responsible_nickname == "abuela" for e in events)


# ── Location ──────────────────────────────────────────────────────────────────

def test_expand_uses_place_alias_when_provided():
    routine = _colegio_routine()
    events = expand_routines_for_day([routine], "2026-04-20")
    assert events[0].location == "colegio"


def test_expand_falls_back_to_place_name():
    routine = _colegio_routine(place_alias=None)
    events = expand_routines_for_day([routine], "2026-04-20")
    assert events[0].location == "Colegio San Juan"


def test_expand_infers_location_from_title_when_missing():
    routine = _colegio_routine(place_alias=None, place_name=None, title="Club Regatas")
    known = [KnownPlace(alias="club", name="Club Regatas", address="X")]
    events = expand_routines_for_day([routine], "2026-04-20", known_places=known)
    # El alias "club" aparece en el título → se usa como ubicación.
    assert events and events[0].location == "club"


# ── IDs y alerts ──────────────────────────────────────────────────────────────

def test_expand_generates_distinct_ids_per_extremo():
    routine = _colegio_routine()
    events = expand_routines_for_day([routine], "2026-04-20")
    ids = {e.id for e in events}
    assert len(ids) == 2
    assert all(e.id.startswith("routine:") for e in events)


def test_expand_disables_alerts_on_virtual_events():
    routine = _colegio_routine()
    events = expand_routines_for_day([routine], "2026-04-20")
    assert all(e.alerts_enabled is False for e in events)


# ── Robustez ──────────────────────────────────────────────────────────────────

def test_expand_handles_invalid_date_string():
    routine = _colegio_routine()
    events = expand_routines_for_day([routine], "no-es-fecha")
    assert events == []


def test_expand_empty_routines_returns_empty():
    assert expand_routines_for_day([], "2026-04-20") == []
