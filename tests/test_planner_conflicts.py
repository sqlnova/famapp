"""Tests para core.planner.conflicts."""
from __future__ import annotations

from datetime import datetime, time

from core.models import (
    AvailabilityWindow,
    ConflictKind,
    ConflictSeverity,
    FamilyMember,
    LogisticsBlock,
    LogisticsBlockKind,
    SupportNetworkMember,
    SupportRole,
)
from core.planner.conflicts import (
    AvailabilityIndex,
    detect_conflicts,
    detect_driver_unauthorized,
    detect_orphan_minor,
    detect_spatial,
    detect_temporal_person,
    detect_travel_infeasible,
)


def _block(
    *,
    title: str = "x",
    start: datetime,
    end: datetime,
    responsible: str | None = None,
    members: list[str] | None = None,
    location_alias: str | None = None,
    kind: LogisticsBlockKind = LogisticsBlockKind.PICKUP,
) -> LogisticsBlock:
    return LogisticsBlock(
        kind=kind,
        title=title,
        start=start,
        end=end,
        location_alias=location_alias,
        location_name=location_alias,
        members=members or [],
        responsible=responsible,
    )


# ── temporal_person ──────────────────────────────────────────────────────────

def test_temporal_person_detects_same_responsible_overlap():
    a = _block(
        title="A", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="papa", location_alias="club",
    )
    b = _block(
        title="B", start=datetime(2026, 4, 19, 17, 30), end=datetime(2026, 4, 19, 18, 30),
        responsible="papa", location_alias="colegio",
    )
    conflicts = detect_temporal_person([a, b])
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.kind == ConflictKind.TEMPORAL_PERSON
    assert c.severity == ConflictSeverity.BLOCKER
    assert set(c.block_ids) == {a.id, b.id}


def test_temporal_person_ignores_non_overlapping():
    a = _block(
        title="A", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 17, 30),
        responsible="papa",
    )
    b = _block(
        title="B", start=datetime(2026, 4, 19, 18), end=datetime(2026, 4, 19, 19),
        responsible="papa",
    )
    assert detect_temporal_person([a, b]) == []


def test_temporal_person_ignores_different_responsibles():
    a = _block(
        title="A", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="papa",
    )
    b = _block(
        title="B", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="mama",
    )
    assert detect_temporal_person([a, b]) == []


def test_temporal_person_skips_unassigned():
    a = _block(title="A", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18))
    b = _block(
        title="B", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="papa",
    )
    assert detect_temporal_person([a, b]) == []


# ── spatial ──────────────────────────────────────────────────────────────────

def test_spatial_conflict_two_places_one_adult():
    a = _block(
        title="club", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="club",
    )
    b = _block(
        title="colegio", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="colegio",
    )
    availability = AvailabilityIndex(windows=[
        AvailabilityWindow(
            member_nickname="papa", weekday=6,
            start=time(16, 0), end=time(20, 0),
        ),
    ])
    conflicts = detect_spatial([a, b], adults_pool=["papa"], availability=availability)
    assert len(conflicts) == 1
    assert conflicts[0].kind == ConflictKind.SPATIAL
    assert conflicts[0].severity == ConflictSeverity.BLOCKER


def test_spatial_no_conflict_when_enough_adults():
    a = _block(
        title="club", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="club",
    )
    b = _block(
        title="colegio", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="colegio",
    )
    availability = AvailabilityIndex(windows=[
        AvailabilityWindow(
            member_nickname=m, weekday=6,
            start=time(16), end=time(20),
        ) for m in ("papa", "mama")
    ])
    conflicts = detect_spatial([a, b], adults_pool=["papa", "mama"], availability=availability)
    assert conflicts == []


def test_spatial_ignored_when_same_location():
    a = _block(
        title="club A", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="club",
    )
    b = _block(
        title="club B", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        location_alias="club",
    )
    conflicts = detect_spatial([a, b], adults_pool=["papa"], availability=AvailabilityIndex())
    assert conflicts == []


# ── travel_infeasible ────────────────────────────────────────────────────────

def test_travel_infeasible_detects_tight_gap():
    a = _block(
        title="colegio", start=datetime(2026, 4, 19, 13), end=datetime(2026, 4, 19, 13, 30),
        responsible="mama", location_alias="colegio",
    )
    b = _block(
        title="club", start=datetime(2026, 4, 19, 13, 35), end=datetime(2026, 4, 19, 14),
        responsible="mama", location_alias="club",
    )
    # 5 min de hueco, 20 min de traslado → conflicto
    conflicts = detect_travel_infeasible([a, b])
    assert len(conflicts) == 1
    assert conflicts[0].kind == ConflictKind.TRAVEL_INFEASIBLE


def test_travel_infeasible_no_conflict_when_enough_time():
    a = _block(
        title="colegio", start=datetime(2026, 4, 19, 13), end=datetime(2026, 4, 19, 13, 30),
        responsible="mama", location_alias="colegio",
    )
    b = _block(
        title="club", start=datetime(2026, 4, 19, 14, 30), end=datetime(2026, 4, 19, 15),
        responsible="mama", location_alias="club",
    )
    assert detect_travel_infeasible([a, b]) == []


def test_travel_infeasible_custom_travel_fn():
    a = _block(
        title="a", start=datetime(2026, 4, 19, 13), end=datetime(2026, 4, 19, 13, 30),
        responsible="mama", location_alias="x",
    )
    b = _block(
        title="b", start=datetime(2026, 4, 19, 13, 40), end=datetime(2026, 4, 19, 14),
        responsible="mama", location_alias="y",
    )
    # Custom: 5 min → alcanza
    assert detect_travel_infeasible([a, b], travel_time_fn=lambda o, d: 5) == []
    # Custom: 30 min → no alcanza
    assert len(detect_travel_infeasible([a, b], travel_time_fn=lambda o, d: 30)) == 1


# ── driver ──────────────────────────────────────────────────────────────────

def test_driver_unauthorized_unknown_name():
    block = _block(
        title="x", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="fantasma",
    )
    family = [FamilyMember(name="Papá", nickname="papa", whatsapp_number="+54")]
    conflicts = detect_driver_unauthorized([block], family=family, support=[])
    assert len(conflicts) == 1
    assert conflicts[0].reason_code == "unknown_responsible"


def test_driver_cannot_drive_for_pickup():
    block = _block(
        title="retiro", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="abuela", kind=LogisticsBlockKind.PICKUP,
    )
    support = [SupportNetworkMember(
        name="Abuela", nickname="abuela", role=SupportRole.GRANDPARENT,
        can_drive=False,
    )]
    conflicts = detect_driver_unauthorized([block], family=[], support=support)
    assert any(c.reason_code == "cannot_drive" for c in conflicts)


def test_driver_kind_not_allowed():
    block = _block(
        title="retiro", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="vecina", kind=LogisticsBlockKind.ERRAND,
    )
    support = [SupportNetworkMember(
        name="Vecina", nickname="vecina",
        allowed_kinds=[LogisticsBlockKind.PICKUP],
    )]
    conflicts = detect_driver_unauthorized([block], family=[], support=support)
    assert any(c.reason_code == "kind_not_allowed" for c in conflicts)


def test_driver_child_not_allowed():
    block = _block(
        title="retiro Gaetano", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="nanny", members=["Gaetano"],
    )
    support = [SupportNetworkMember(
        name="Nanny", nickname="nanny",
        allowed_children=["Giuseppe", "Isabella"],
    )]
    conflicts = detect_driver_unauthorized([block], family=[], support=support)
    assert any(c.reason_code == "child_not_allowed" for c in conflicts)


def test_driver_core_member_never_flagged():
    block = _block(
        title="x", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="papa",
    )
    family = [FamilyMember(name="Papá", nickname="papa", whatsapp_number="+54")]
    assert detect_driver_unauthorized([block], family=family, support=[]) == []


# ── orphan_minor ────────────────────────────────────────────────────────────

def test_orphan_minor_block_with_minor_no_responsible():
    block = _block(
        title="retiro", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        members=["giuseppe"], kind=LogisticsBlockKind.PICKUP,
    )
    family = [FamilyMember(name="Giuseppe", nickname="giuseppe", whatsapp_number="", is_minor=True)]
    conflicts = detect_orphan_minor([block], family=family)
    assert len(conflicts) == 1
    assert conflicts[0].kind == ConflictKind.ORPHAN_MINOR


def test_orphan_minor_ignored_when_stay():
    block = _block(
        title="clase", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        members=["giuseppe"], kind=LogisticsBlockKind.STAY,
    )
    family = [FamilyMember(name="Giuseppe", nickname="giuseppe", whatsapp_number="", is_minor=True)]
    assert detect_orphan_minor([block], family=family) == []


def test_orphan_minor_not_flagged_when_has_responsible():
    block = _block(
        title="retiro", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        members=["giuseppe"], responsible="papa",
    )
    family = [
        FamilyMember(name="Papá", nickname="papa", whatsapp_number="", is_minor=False),
        FamilyMember(name="Giuseppe", nickname="giuseppe", whatsapp_number="", is_minor=True),
    ]
    assert detect_orphan_minor([block], family=family) == []


# ── Orquestador ──────────────────────────────────────────────────────────────

def test_detect_conflicts_integrates_all():
    a = _block(
        title="club", start=datetime(2026, 4, 19, 17), end=datetime(2026, 4, 19, 18),
        responsible="papa", location_alias="club",
    )
    b = _block(
        title="colegio", start=datetime(2026, 4, 19, 17, 30), end=datetime(2026, 4, 19, 18, 30),
        responsible="papa", location_alias="colegio",
    )
    conflicts = detect_conflicts([a, b])
    kinds = {c.kind for c in conflicts}
    assert ConflictKind.TEMPORAL_PERSON in kinds
