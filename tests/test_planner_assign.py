"""Tests para core.planner.assign."""
from __future__ import annotations

from datetime import datetime, time

from core.models import (
    AvailabilityWindow,
    FamilyMember,
    LogisticsBlock,
    LogisticsBlockKind,
    PreferenceProfile,
    SupportNetworkMember,
    SupportRole,
)
from core.planner.assign import AssignmentContext, assign_responsibles
from core.planner.conflicts import AvailabilityIndex


def _block(
    *,
    title: str = "x",
    start: datetime,
    end: datetime,
    responsible: str | None = None,
    members: list[str] | None = None,
    location_alias: str | None = "club",
    kind: LogisticsBlockKind = LogisticsBlockKind.PICKUP,
) -> LogisticsBlock:
    return LogisticsBlock(
        kind=kind,
        title=title,
        start=start,
        end=end,
        location_alias=location_alias,
        members=members or [],
        responsible=responsible,
    )


def _family():
    return [
        FamilyMember(name="Papá", nickname="papa", whatsapp_number="+54"),
        FamilyMember(name="Mamá", nickname="mama", whatsapp_number="+54"),
    ]


def _ctx(
    family=None, support=None, availability=None, preferences=None, travel_fn=None,
):
    kwargs = dict(
        family=family if family is not None else _family(),
        support=support or [],
        availability=availability or AvailabilityIndex(),
        preferences=preferences or [],
    )
    if travel_fn is not None:
        kwargs["travel_time_fn"] = travel_fn
    return AssignmentContext(**kwargs)


def test_assign_respects_preassigned():
    a = _block(
        title="ya asignado",
        start=datetime(2026, 4, 19, 17),
        end=datetime(2026, 4, 19, 18),
        responsible="papa",
    )
    b = _block(
        title="pendiente",
        start=datetime(2026, 4, 19, 19),
        end=datetime(2026, 4, 19, 20),
    )
    out_blocks, assignments = assign_responsibles([a, b], _ctx())
    assert out_blocks[0].responsible == "papa"  # no se toca
    assert len(assignments) == 1
    assert assignments[0].block_id == b.id


def test_assign_picks_available_adult():
    b = _block(
        title="pendiente",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
    )
    avail = AvailabilityIndex(windows=[
        AvailabilityWindow(
            member_nickname="mama", weekday=6,
            start=time(17), end=time(21),
        ),
    ])
    ctx = _ctx(availability=avail)
    _, assignments = assign_responsibles([b], ctx)
    assert len(assignments) == 1
    assert assignments[0].responsible_nickname == "mama"
    assert assignments[0].confidence > 0


def test_assign_uses_preference_profile():
    b = _block(
        title="club",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
        kind=LogisticsBlockKind.PICKUP,
        location_alias="club",
    )
    prefs = [
        PreferenceProfile(
            member_nickname="papa",
            place_alias="club",
            block_kind=LogisticsBlockKind.PICKUP,
            score=0.95,
            sample_size=10,
        ),
        PreferenceProfile(
            member_nickname="mama",
            place_alias="club",
            block_kind=LogisticsBlockKind.PICKUP,
            score=0.1,
            sample_size=10,
        ),
    ]
    ctx = _ctx(preferences=prefs)
    _, assignments = assign_responsibles([b], ctx)
    assert assignments[0].responsible_nickname == "papa"


def test_assign_avoids_concentrating_all_on_one():
    # 4 bloques no-solapados. Con pesos default, balance de carga debe
    # evitar que un solo adulto se lleve todo.
    blocks = [
        _block(
            title=f"b{i}",
            start=datetime(2026, 4, 19, 8 + i * 2),
            end=datetime(2026, 4, 19, 8 + i * 2 + 1),
        )
        for i in range(4)
    ]
    _, assignments = assign_responsibles(blocks, _ctx())
    responsibles = {a.responsible_nickname for a in assignments}
    # Debe distribuir entre al menos 2 adultos
    assert len(responsibles) >= 2


def test_assign_respects_support_network_constraints():
    # Bloque requiere conducción pero abuela no maneja.
    # Abuela no debería ser elegida aunque tenga alta preferencia.
    b = _block(
        title="x",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
        kind=LogisticsBlockKind.PICKUP,
    )
    support = [SupportNetworkMember(
        name="Abuela", nickname="abuela", role=SupportRole.GRANDPARENT,
        can_drive=False,
    )]
    prefs = [
        PreferenceProfile(
            member_nickname="abuela", score=0.99, sample_size=50,
        ),
    ]
    ctx = _ctx(support=support, preferences=prefs)
    _, assignments = assign_responsibles([b], ctx)
    assert assignments[0].responsible_nickname != "abuela"


def test_assign_explanation_mentions_reason():
    b = _block(
        title="x",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
    )
    prefs = [
        PreferenceProfile(
            member_nickname="papa", score=0.9, sample_size=10,
        ),
    ]
    ctx = _ctx(preferences=prefs)
    _, assignments = assign_responsibles([b], ctx)
    assert assignments[0].explanation
    assert "papa" in assignments[0].explanation.lower() or "mama" in assignments[0].explanation.lower()


def test_assign_returns_empty_when_nothing_pending():
    a = _block(
        title="a",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
        responsible="papa",
    )
    out, assignments = assign_responsibles([a], _ctx())
    assert assignments == []
    assert out[0].responsible == "papa"


def test_assign_includes_alternatives():
    b = _block(
        title="x",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
    )
    _, assignments = assign_responsibles([b], _ctx())
    # Con 2 adultos, debe haber al menos 1 alternativa
    assert len(assignments[0].alternatives) >= 1


def test_assign_handles_empty_family_gracefully():
    b = _block(
        title="x",
        start=datetime(2026, 4, 19, 18),
        end=datetime(2026, 4, 19, 19),
    )
    ctx = _ctx(family=[])
    out, assignments = assign_responsibles([b], ctx)
    # Sin familia ni soporte → no hay candidatos, bloque queda sin asignar
    assert out[0].responsible is None
    assert assignments == []
