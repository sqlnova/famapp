"""Tests para core.planner.merge."""
from __future__ import annotations

from datetime import datetime, timedelta

from core.models import LogisticsBlock, LogisticsBlockKind
from core.planner.merge import merge_compatible, mergeable


def _block(
    title: str,
    start: datetime,
    end: datetime,
    *,
    kind: LogisticsBlockKind = LogisticsBlockKind.PICKUP,
    location_alias: str | None = "club",
    members: list[str] | None = None,
    responsible: str | None = None,
) -> LogisticsBlock:
    return LogisticsBlock(
        kind=kind,
        title=title,
        start=start,
        end=end,
        location_alias=location_alias,
        location_name="Club Regatas" if location_alias == "club" else None,
        members=members or [],
        responsible=responsible,
    )


# ── mergeable predicate ───────────────────────────────────────────────────────

def test_mergeable_same_location_same_kind_overlapping_times():
    a = _block("Retirar a Giuseppe", datetime(2026, 4, 19, 18, 0), datetime(2026, 4, 19, 18, 15))
    b = _block("Retirar a Isabella", datetime(2026, 4, 19, 18, 5), datetime(2026, 4, 19, 18, 20))
    assert mergeable(a, b) is True


def test_not_mergeable_different_locations():
    a = _block(
        "Retirar a Giuseppe",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        location_alias="club",
    )
    b = _block(
        "Retirar a Isabella",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        location_alias="colegio",
    )
    assert mergeable(a, b) is False


def test_not_mergeable_pickup_vs_drop():
    a = _block(
        "Llevar a Giuseppe",
        datetime(2026, 4, 19, 17, 0),
        datetime(2026, 4, 19, 17, 15),
        kind=LogisticsBlockKind.DROP,
    )
    b = _block(
        "Retirar a Isabella",
        datetime(2026, 4, 19, 17, 0),
        datetime(2026, 4, 19, 17, 15),
        kind=LogisticsBlockKind.PICKUP,
    )
    assert mergeable(a, b) is False


def test_not_mergeable_far_apart_in_time():
    a = _block("A", datetime(2026, 4, 19, 17, 0), datetime(2026, 4, 19, 17, 15))
    b = _block("B", datetime(2026, 4, 19, 19, 0), datetime(2026, 4, 19, 19, 15))
    assert mergeable(a, b) is False


def test_not_mergeable_different_responsibles():
    a = _block(
        "Retirar a Giuseppe",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        responsible="papa",
    )
    b = _block(
        "Retirar a Isabella",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        responsible="mama",
    )
    assert mergeable(a, b) is False


def test_mergeable_when_only_one_has_responsible():
    a = _block(
        "Retirar a Giuseppe",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        responsible="papa",
    )
    b = _block(
        "Retirar a Isabella",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        responsible=None,
    )
    assert mergeable(a, b) is True


def test_mergeable_unknown_kind_compatible_with_known():
    a = _block(
        "X",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        kind=LogisticsBlockKind.UNKNOWN,
    )
    b = _block(
        "Retirar a Giuseppe",
        datetime(2026, 4, 19, 18, 0),
        datetime(2026, 4, 19, 18, 15),
        kind=LogisticsBlockKind.PICKUP,
    )
    assert mergeable(a, b) is True


# ── merge_compatible integration ──────────────────────────────────────────────

def test_merge_two_pickups_same_location_produces_one_block():
    blocks = [
        _block(
            "Retirar a Giuseppe del club",
            datetime(2026, 4, 19, 18, 0),
            datetime(2026, 4, 19, 18, 15),
            members=["Giuseppe"],
        ),
        _block(
            "Retirar a Isabella del club",
            datetime(2026, 4, 19, 18, 10),
            datetime(2026, 4, 19, 18, 20),
            members=["Isabella"],
        ),
    ]
    merged = merge_compatible(blocks)
    assert len(merged) == 1
    out = merged[0]
    assert set(out.members) == {"Giuseppe", "Isabella"}
    assert out.location_alias == "club"
    assert out.kind == LogisticsBlockKind.PICKUP
    assert out.start == datetime(2026, 4, 19, 18, 0)
    assert out.end == datetime(2026, 4, 19, 18, 20)
    assert len(out.merged_from) == 2
    assert "Giuseppe" in out.title and "Isabella" in out.title


def test_merge_is_transitive():
    # A mergeable con B, B mergeable con C → los tres colapsan.
    t0 = datetime(2026, 4, 19, 18, 0)
    blocks = [
        _block("a", t0, t0 + timedelta(minutes=10), members=["A"]),
        _block("b", t0 + timedelta(minutes=5), t0 + timedelta(minutes=15), members=["B"]),
        _block("c", t0 + timedelta(minutes=12), t0 + timedelta(minutes=20), members=["C"]),
    ]
    merged = merge_compatible(blocks)
    assert len(merged) == 1
    assert set(merged[0].members) == {"A", "B", "C"}


def test_merge_preserves_non_mergeable_blocks():
    blocks = [
        _block(
            "Retirar del club",
            datetime(2026, 4, 19, 18, 0),
            datetime(2026, 4, 19, 18, 15),
        ),
        _block(
            "Retirar del colegio",
            datetime(2026, 4, 19, 18, 0),
            datetime(2026, 4, 19, 18, 15),
            location_alias="colegio",
        ),
    ]
    merged = merge_compatible(blocks)
    assert len(merged) == 2


def test_merge_empty_returns_empty():
    assert merge_compatible([]) == []


def test_merge_single_block_returns_itself():
    b = _block("solo", datetime(2026, 4, 19, 18, 0), datetime(2026, 4, 19, 18, 15))
    merged = merge_compatible([b])
    assert merged == [b]


def test_merge_does_not_combine_pickup_and_drop_same_place():
    blocks = [
        _block(
            "Llevar a Giuseppe al club",
            datetime(2026, 4, 19, 17, 0),
            datetime(2026, 4, 19, 17, 10),
            kind=LogisticsBlockKind.DROP,
        ),
        _block(
            "Retirar a Isabella del club",
            datetime(2026, 4, 19, 17, 0),
            datetime(2026, 4, 19, 17, 10),
            kind=LogisticsBlockKind.PICKUP,
        ),
    ]
    merged = merge_compatible(blocks)
    assert len(merged) == 2


def test_merge_output_is_sorted_by_start():
    blocks = [
        _block(
            "b",
            datetime(2026, 4, 19, 19, 0),
            datetime(2026, 4, 19, 19, 15),
            location_alias="colegio",
        ),
        _block(
            "a",
            datetime(2026, 4, 19, 18, 0),
            datetime(2026, 4, 19, 18, 15),
        ),
    ]
    merged = merge_compatible(blocks)
    assert merged[0].start < merged[1].start
