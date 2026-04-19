"""Tests para core.planner.feasibility."""
from __future__ import annotations

from datetime import datetime

from core.models import (
    Assignment,
    Conflict,
    ConflictKind,
    ConflictSeverity,
    LogisticsBlock,
    LogisticsBlockKind,
    PlanStatus,
)
from core.planner.feasibility import feasibility


def _block(responsible: str | None = "papa") -> LogisticsBlock:
    return LogisticsBlock(
        kind=LogisticsBlockKind.PICKUP,
        title="x",
        start=datetime(2026, 4, 19, 17),
        end=datetime(2026, 4, 19, 18),
        responsible=responsible,
    )


def test_feasibility_empty_plan_is_calma():
    fb = feasibility([], [], [])
    assert fb.status == PlanStatus.CALMA
    assert fb.score == 1.0


def test_feasibility_all_assigned_no_conflicts():
    blocks = [_block() for _ in range(3)]
    assignments = [
        Assignment(block_id=b.id, responsible_nickname="papa", confidence=0.9)
        for b in blocks
    ]
    fb = feasibility(blocks, [], assignments)
    assert fb.status == PlanStatus.CALMA
    assert fb.score > 0.9


def test_feasibility_conflicts_drop_score():
    blocks = [_block() for _ in range(4)]
    conflicts = [
        Conflict(
            kind=ConflictKind.TEMPORAL_PERSON,
            severity=ConflictSeverity.BLOCKER,
            block_ids=[blocks[0].id, blocks[1].id],
        )
    ]
    fb = feasibility(blocks, conflicts, [])
    assert fb.blockers == 1
    assert fb.score < 1.0


def test_feasibility_orphans_drop_score():
    blocks = [_block(responsible=None) for _ in range(2)] + [_block() for _ in range(2)]
    fb = feasibility(blocks, [], [])
    assert fb.orphan_component < 1.0


def test_feasibility_travel_component_reflects_travel_conflicts():
    blocks = [_block() for _ in range(4)]
    conflicts = [
        Conflict(
            kind=ConflictKind.TRAVEL_INFEASIBLE,
            severity=ConflictSeverity.WARNING,
            block_ids=[blocks[0].id, blocks[1].id],
        )
    ]
    fb = feasibility(blocks, conflicts, [])
    assert fb.travel_component < 1.0
    assert fb.warnings == 1


def test_feasibility_severe_plan_marks_revisar():
    # Plan con muchos conflictos y huérfanos
    blocks = [_block(responsible=None) for _ in range(4)]
    conflicts = [
        Conflict(
            kind=ConflictKind.SPATIAL,
            severity=ConflictSeverity.BLOCKER,
            block_ids=[b.id for b in blocks],
        )
    ]
    fb = feasibility(blocks, conflicts, [])
    assert fb.status == PlanStatus.REVISAR


def test_feasibility_status_thresholds():
    # Score ≥ 0.85 → calma
    blocks = [_block() for _ in range(10)]
    assignments = [
        Assignment(block_id=b.id, responsible_nickname="papa", confidence=1.0)
        for b in blocks
    ]
    fb = feasibility(blocks, [], assignments)
    assert fb.status == PlanStatus.CALMA

    # Con un blocker en 10 bloques → cae pero no debería llegar a REVISAR si
    # el resto está bien.
    conflicts = [Conflict(
        kind=ConflictKind.TEMPORAL_PERSON,
        severity=ConflictSeverity.BLOCKER,
        block_ids=[blocks[0].id, blocks[1].id],
    )]
    fb2 = feasibility(blocks, conflicts, assignments)
    assert fb2.score < fb.score
