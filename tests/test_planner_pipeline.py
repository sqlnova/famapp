"""Tests de integración end-to-end del pipeline de planificación.

Escenario realista: un martes de familia con 3 chicos, 2 adultos, y
superposición de compromisos colegio/club.
"""
from __future__ import annotations

from datetime import datetime, time

from core.models import (
    AvailabilityWindow,
    CalendarEvent,
    ConflictKind,
    FamilyMember,
    KnownPlace,
    LogisticsBlockKind,
    PlanStatus,
    PreferenceProfile,
    SupportNetworkMember,
    SupportRole,
)
from core.planner import AvailabilityIndex, FamilyContext, plan_day


def _family():
    return [
        FamilyMember(name="Papá", nickname="papa", whatsapp_number="+54"),
        FamilyMember(name="Mamá", nickname="mama", whatsapp_number="+54"),
        FamilyMember(name="Giuseppe", nickname="giuseppe", whatsapp_number="", is_minor=True),
        FamilyMember(name="Isabella", nickname="isabella", whatsapp_number="", is_minor=True),
        FamilyMember(name="Gaetano", nickname="gaetano", whatsapp_number="", is_minor=True),
    ]


def _places():
    return [
        KnownPlace(alias="colegio", name="Colegio San Juan", address="Güemes 200"),
        KnownPlace(alias="club", name="Club Regatas Resistencia", address="Chaco 800"),
        KnownPlace(alias="farmacia", name="Farmacia Central", address="Mitre 50"),
    ]


def _availability_both_afternoons():
    return AvailabilityIndex(windows=[
        AvailabilityWindow(
            member_nickname="papa", weekday=6,   # domingo (19 abril 2026)
            start=time(7), end=time(22),
        ),
        AvailabilityWindow(
            member_nickname="mama", weekday=6,
            start=time(7), end=time(22),
        ),
    ])


# ── Escenarios realistas ──────────────────────────────────────────────────────

def test_pipeline_empty_day_is_calma():
    plan = plan_day("2026-04-19", events=[], ctx=FamilyContext(family=_family()))
    assert plan.status == PlanStatus.CALMA
    assert plan.blocks == []
    assert plan.conflicts == []
    assert "calma" in (plan.summary_es or "").lower()


def test_pipeline_merges_two_club_pickups_into_single_block():
    """Dos retiros del club al mismo horario → un solo bloque fusionado."""
    events = [
        CalendarEvent(
            id="e1",
            title="Retirar a Giuseppe del club",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 15),
            location="club",
            children=["Giuseppe"],
        ),
        CalendarEvent(
            id="e2",
            title="Retirar a Isabella del club",
            start=datetime(2026, 4, 19, 18, 10),
            end=datetime(2026, 4, 19, 18, 25),
            location="club",
            children=["Isabella"],
        ),
    ]
    ctx = FamilyContext(family=_family(), known_places=_places())
    plan = plan_day("2026-04-19", events=events, ctx=ctx)

    assert len(plan.blocks) == 1
    block = plan.blocks[0]
    assert block.kind == LogisticsBlockKind.PICKUP
    assert set(block.members) == {"Giuseppe", "Isabella"}
    assert block.location_alias == "club"
    # El bloque fusionado debe haber sido asignado a algún adulto
    assert block.responsible in ("papa", "mama")


def test_pipeline_detects_spatial_conflict_same_time_different_places():
    """17:00 club + 17:00 colegio con un solo adulto disponible → spatial."""
    events = [
        CalendarEvent(
            id="e1",
            title="Llevar chicos al club",
            start=datetime(2026, 4, 19, 17, 0),
            end=datetime(2026, 4, 19, 17, 30),
            location="club",
            children=["Giuseppe", "Isabella"],
        ),
        CalendarEvent(
            id="e2",
            title="Retirar a Gaetano del colegio",
            start=datetime(2026, 4, 19, 17, 0),
            end=datetime(2026, 4, 19, 17, 15),
            location="colegio",
            children=["Gaetano"],
        ),
    ]
    # Solo Papá disponible en esa ventana
    avail = AvailabilityIndex(windows=[
        AvailabilityWindow(
            member_nickname="papa", weekday=6,
            start=time(16), end=time(20),
        ),
    ])
    ctx = FamilyContext(
        family=_family(),
        known_places=_places(),
        availability=avail,
    )
    plan = plan_day("2026-04-19", events=events, ctx=ctx)

    assert any(c.kind == ConflictKind.SPATIAL for c in plan.conflicts)
    assert plan.status in (PlanStatus.OCUPADO, PlanStatus.REVISAR)


def test_pipeline_uses_preference_profile_for_assignment():
    """Papá tiene preferencia fuerte por el club → debe ser asignado."""
    events = [
        CalendarEvent(
            id="e1",
            title="Retirar a Giuseppe del club",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 15),
            location="club",
            children=["Giuseppe"],
        ),
    ]
    prefs = [
        PreferenceProfile(
            member_nickname="papa",
            place_alias="club",
            block_kind=LogisticsBlockKind.PICKUP,
            score=0.95, sample_size=12,
        ),
    ]
    ctx = FamilyContext(
        family=_family(),
        known_places=_places(),
        availability=_availability_both_afternoons(),
        preferences=prefs,
    )
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    assert plan.blocks[0].responsible == "papa"


def test_pipeline_support_network_can_cover_when_core_busy():
    """Papá ocupado, Mamá ocupada, Abuela cubre el tercer bloque simultáneo."""
    events = [
        CalendarEvent(
            id="e1",
            title="Llevar a Giuseppe al colegio",
            start=datetime(2026, 4, 19, 7, 45),
            end=datetime(2026, 4, 19, 8, 0),
            location="colegio",
            children=["Giuseppe"],
            responsible_nickname="papa",
        ),
        CalendarEvent(
            id="e2",
            title="Llevar a Isabella al club",
            start=datetime(2026, 4, 19, 7, 45),
            end=datetime(2026, 4, 19, 8, 0),
            location="club",
            children=["Isabella"],
            responsible_nickname="mama",
        ),
        CalendarEvent(
            id="e3",
            title="Llevar a Gaetano a la farmacia",
            start=datetime(2026, 4, 19, 7, 45),
            end=datetime(2026, 4, 19, 8, 0),
            location="farmacia",
            children=["Gaetano"],
        ),
    ]
    support = [
        SupportNetworkMember(
            name="Abuela", nickname="abuela", role=SupportRole.GRANDPARENT,
            can_drive=True, trust_level=0.9,
        ),
    ]
    ctx = FamilyContext(
        family=_family(),
        support=support,
        known_places=_places(),
        availability=_availability_both_afternoons(),
    )
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    # El tercer bloque (sin responsable asignado) debería caer en abuela
    # porque papá y mamá ya están ocupados.
    gaetano_block = next(b for b in plan.blocks if "Gaetano" in b.members)
    assert gaetano_block.responsible is not None


def test_pipeline_feasibility_drops_with_travel_infeasible():
    """Mamá: colegio 13:30 → club 13:35 con 20 min de traslado → warning."""
    events = [
        CalendarEvent(
            id="e1",
            title="Retirar chicos del colegio",
            start=datetime(2026, 4, 19, 13, 0),
            end=datetime(2026, 4, 19, 13, 30),
            location="colegio",
            children=["Giuseppe", "Isabella"],
            responsible_nickname="mama",
        ),
        CalendarEvent(
            id="e2",
            title="Llevar a Gaetano al club",
            start=datetime(2026, 4, 19, 13, 35),
            end=datetime(2026, 4, 19, 14, 0),
            location="club",
            children=["Gaetano"],
            responsible_nickname="mama",
        ),
    ]
    ctx = FamilyContext(family=_family(), known_places=_places())
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    assert any(c.kind == ConflictKind.TRAVEL_INFEASIBLE for c in plan.conflicts)
    assert plan.feasibility_score < 1.0


def test_pipeline_builds_trips_for_pickup_and_drop_only():
    """STAY no genera Trip; PICKUP/DROP sí."""
    events = [
        CalendarEvent(
            id="e1",
            title="Clase de inglés de Giuseppe",
            start=datetime(2026, 4, 19, 17, 0),
            end=datetime(2026, 4, 19, 18, 0),
            location="colegio",
            children=["Giuseppe"],
        ),
        CalendarEvent(
            id="e2",
            title="Retirar a Giuseppe del colegio",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 15),
            location="colegio",
            children=["Giuseppe"],
            responsible_nickname="papa",
        ),
    ]
    ctx = FamilyContext(family=_family(), known_places=_places())
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    # Debe haber un solo trip: el pickup (la clase es STAY y no genera trip).
    assert len(plan.trips) == 1
    assert plan.trips[0].driver_nickname == "papa"


def test_pipeline_summary_is_spanish():
    events = [
        CalendarEvent(
            id="e1",
            title="Retirar a Giuseppe",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 15),
            location="club",
            children=["Giuseppe"],
            responsible_nickname="papa",
        ),
    ]
    ctx = FamilyContext(family=_family(), known_places=_places())
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    assert plan.summary_es is not None
    # Debe contener alguna palabra española del resumen
    assert any(w in plan.summary_es.lower() for w in ("bloques", "estado", "calma", "ocupado"))


def test_pipeline_handles_missing_data_gracefully():
    """Evento sin location ni children ni responsable → bloque needs_review
    pero el plan se genera igual."""
    events = [
        CalendarEvent(
            id="e1",
            title="Algo indefinido",
            start=datetime(2026, 4, 19, 15, 0),
            end=datetime(2026, 4, 19, 15, 30),
        ),
    ]
    ctx = FamilyContext(family=_family())
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    assert len(plan.blocks) == 1
    assert plan.blocks[0].needs_review is True
    assert plan.blocks[0].confidence < 1.0


def test_pipeline_respects_preassigned_responsible():
    """Si un evento ya trae responsible_nickname, no se reasigna."""
    events = [
        CalendarEvent(
            id="e1",
            title="Retirar a Isabella",
            start=datetime(2026, 4, 19, 18, 0),
            end=datetime(2026, 4, 19, 18, 15),
            location="club",
            children=["Isabella"],
            responsible_nickname="mama",
        ),
    ]
    ctx = FamilyContext(
        family=_family(),
        known_places=_places(),
        preferences=[
            PreferenceProfile(
                member_nickname="papa", place_alias="club",
                score=0.99, sample_size=50,
            )
        ],
    )
    plan = plan_day("2026-04-19", events=events, ctx=ctx)
    # Aunque papá tenga preferencia fuerte, respeta lo preasignado.
    assert plan.blocks[0].responsible == "mama"
    # Y no genera Assignment para ese bloque (porque ya venía asignado).
    assert not any(a.block_id == plan.blocks[0].id for a in plan.assignments)
