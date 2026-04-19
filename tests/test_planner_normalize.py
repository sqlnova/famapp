"""Tests para core.planner.normalize."""
from __future__ import annotations

from datetime import datetime, timedelta

from core.models import CalendarEvent, KnownPlace, LogisticsBlockKind
from core.planner.normalize import (
    classify_kind,
    normalize_event,
    normalize_events,
    resolve_place,
)


# ── classify_kind ─────────────────────────────────────────────────────────────

def test_classify_kind_pickup_variants():
    assert classify_kind("Retirar a Giuseppe del club") == LogisticsBlockKind.PICKUP
    assert classify_kind("Buscar a Isabella") == LogisticsBlockKind.PICKUP
    assert classify_kind("Pasar a buscar a los chicos") == LogisticsBlockKind.PICKUP


def test_classify_kind_drop_variants():
    assert classify_kind("Llevar a Giuseppe al colegio") == LogisticsBlockKind.DROP
    assert classify_kind("Dejar a los chicos en el club") == LogisticsBlockKind.DROP


def test_classify_kind_stay_variants():
    assert classify_kind("Clase de inglés") == LogisticsBlockKind.STAY
    assert classify_kind("Partido de fútbol") == LogisticsBlockKind.STAY
    assert classify_kind("Cumpleaños de Gaetano") == LogisticsBlockKind.STAY


def test_classify_kind_errand():
    assert classify_kind("Pasar por farmacia") == LogisticsBlockKind.ERRAND
    assert classify_kind("Supermercado") == LogisticsBlockKind.ERRAND


def test_classify_kind_unknown_when_ambiguous():
    assert classify_kind("Algo random") == LogisticsBlockKind.UNKNOWN


def test_classify_kind_case_and_accents_insensitive():
    assert classify_kind("REUNIÓN con profesora") == LogisticsBlockKind.STAY
    assert classify_kind("reunion con profe") == LogisticsBlockKind.STAY


# ── resolve_place ─────────────────────────────────────────────────────────────

def _places():
    return [
        KnownPlace(alias="colegio", name="Colegio San Juan", address="Güemes 200"),
        KnownPlace(alias="club", name="Club Regatas Resistencia", address="Chaco 800"),
        KnownPlace(alias="farmacia", name="Farmacia Central", address="Mitre 50"),
    ]


def test_resolve_place_exact_alias_match():
    place = resolve_place("club", "Retirar a los chicos", _places())
    assert place is not None
    assert place.alias == "club"


def test_resolve_place_from_title_when_location_missing():
    place = resolve_place(None, "Retirar a Giuseppe del club", _places())
    assert place is not None
    assert place.alias == "club"


def test_resolve_place_fuzzy_typo():
    place = resolve_place("clup", "nada", _places())  # 1 char off
    assert place is not None
    assert place.alias == "club"


def test_resolve_place_no_match():
    place = resolve_place("algo inventado", "ni idea", _places())
    assert place is None


def test_resolve_place_empty_catalog():
    assert resolve_place("club", "x", []) is None


# ── normalize_event ───────────────────────────────────────────────────────────

def _event(**kwargs) -> CalendarEvent:
    defaults = {
        "title": "Retirar a Giuseppe del club",
        "start": datetime(2026, 4, 19, 18, 0),
        "end": datetime(2026, 4, 19, 18, 15),
    }
    defaults.update(kwargs)
    return CalendarEvent(**defaults)


def test_normalize_event_full_data_high_confidence():
    block = normalize_event(
        _event(
            location="club",
            children=["Giuseppe"],
            responsible_nickname="papa",
        ),
        known_places=_places(),
    )
    assert block.kind == LogisticsBlockKind.PICKUP
    assert block.location_alias == "club"
    assert block.members == ["Giuseppe"]
    assert block.responsible == "papa"
    assert block.confidence == 1.0
    assert block.needs_review is False


def test_normalize_event_missing_responsible_lowers_confidence():
    block = normalize_event(
        _event(location="club", children=["Giuseppe"]),
        known_places=_places(),
    )
    assert block.responsible is None
    assert block.confidence < 1.0
    assert "responsible" in (block.notes or "")


def test_normalize_event_missing_location_lowers_confidence():
    block = normalize_event(
        _event(title="Retirar a Giuseppe", location=None, children=["Giuseppe"]),
        known_places=_places(),
    )
    # No se puede inferir el lugar del título → sin location
    assert block.location_alias is None
    assert block.confidence < 1.0


def test_normalize_event_infers_members_from_title():
    block = normalize_event(
        _event(title="Retirar a Giuseppe del club", children=[]),
        known_places=_places(),
        known_children=["Giuseppe", "Isabella", "Gaetano"],
    )
    assert "Giuseppe" in block.members


def test_normalize_event_unknown_kind_flags_review():
    block = normalize_event(
        _event(title="Cosa misteriosa", location="club", children=["Giuseppe"]),
        known_places=_places(),
    )
    assert block.kind == LogisticsBlockKind.UNKNOWN
    assert block.needs_review is True


def test_normalize_events_handles_iterable():
    events = [
        _event(title="Llevar a Giuseppe al colegio", location="colegio"),
        _event(
            title="Retirar del club",
            location="club",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 30),
        ),
    ]
    blocks = normalize_events(events, known_places=_places())
    assert len(blocks) == 2
    assert blocks[0].kind == LogisticsBlockKind.DROP
    assert blocks[1].kind == LogisticsBlockKind.PICKUP
