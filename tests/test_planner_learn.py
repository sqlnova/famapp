"""Tests para el agregador de feedback → PreferenceProfile."""
from __future__ import annotations

from core.planner.learn import aggregate_preferences


def _row(**kw):
    base = dict(
        action="accept",
        old_responsible=None,
        new_responsible="papa",
        place_alias="club",
        block_kind="pickup",
    )
    base.update(kw)
    return base


# ── Accept ────────────────────────────────────────────────────────────────────

def test_aggregate_accept_increments_positive():
    rows = [_row() for _ in range(5)]
    profiles = aggregate_preferences(rows)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.member_nickname == "papa"
    assert p.place_alias == "club"
    assert p.sample_size == 5
    assert p.score > 0.8  # todo positivo → cerca de 1


def test_aggregate_ignores_below_threshold():
    rows = [_row()]  # sample_size=1 con min_sample_size=2 por default
    assert aggregate_preferences(rows) == []


def test_aggregate_respects_min_sample_size():
    rows = [_row()]
    profiles = aggregate_preferences(rows, min_sample_size=1)
    assert len(profiles) == 1


# ── Override ──────────────────────────────────────────────────────────────────

def test_aggregate_override_adds_positive_to_new_negative_to_old():
    rows = [
        _row(action="override", old_responsible="papa", new_responsible="mama")
        for _ in range(4)
    ]
    profiles = aggregate_preferences(rows)
    by_name = {p.member_nickname: p for p in profiles}
    assert "mama" in by_name and "papa" in by_name
    # Mama tiene 4 positivos, papa 4 negativos.
    assert by_name["mama"].score > 0.7
    assert by_name["papa"].score < 0.3


def test_aggregate_mixed_signals_balance_out():
    rows = [
        _row(action="accept", new_responsible="papa"),
        _row(action="accept", new_responsible="papa"),
        _row(action="override", old_responsible="papa", new_responsible="mama"),
        _row(action="override", old_responsible="papa", new_responsible="mama"),
    ]
    profiles = aggregate_preferences(rows)
    papa = next(p for p in profiles if p.member_nickname == "papa")
    # 2 accept (+) vs 2 override-outgoing (−) → score ≈ 0.5
    assert 0.4 <= papa.score <= 0.6


# ── Segmentación por (lugar, kind) ────────────────────────────────────────────

def test_aggregate_keeps_place_kind_segmentation():
    rows = [
        _row(place_alias="club", block_kind="pickup"),
        _row(place_alias="club", block_kind="pickup"),
        _row(place_alias="colegio", block_kind="drop"),
        _row(place_alias="colegio", block_kind="drop"),
    ]
    profiles = aggregate_preferences(rows)
    # Mismo responsable pero dos perfiles distintos por par place×kind.
    assert len(profiles) == 2
    places = {p.place_alias for p in profiles}
    assert places == {"club", "colegio"}


# ── Robustez ──────────────────────────────────────────────────────────────────

def test_aggregate_empty_returns_empty():
    assert aggregate_preferences([]) == []


def test_aggregate_ignores_action_ignore():
    rows = [_row(action="ignore") for _ in range(5)]
    assert aggregate_preferences(rows) == []


def test_aggregate_skips_rows_without_responsible():
    rows = [_row(new_responsible=None, old_responsible=None) for _ in range(3)]
    assert aggregate_preferences(rows) == []


def test_aggregate_output_is_deterministic():
    rows = [
        _row(new_responsible="papa", place_alias="a"),
        _row(new_responsible="papa", place_alias="b"),
        _row(new_responsible="mama", place_alias="a"),
        _row(new_responsible="mama", place_alias="b"),
    ]
    p1 = aggregate_preferences(rows, min_sample_size=1)
    p2 = aggregate_preferences(list(reversed(rows)), min_sample_size=1)
    assert [(p.member_nickname, p.place_alias) for p in p1] == \
           [(p.member_nickname, p.place_alias) for p in p2]
