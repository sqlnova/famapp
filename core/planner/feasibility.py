"""Score de factibilidad de un plan diario.

Combina 4 señales en un único número [0, 1] que traduce a estado:
- conflictos no resueltos
- confianza promedio de las asignaciones
- desajustes de tiempo de viaje (travel_infeasible)
- bloques huérfanos (sin responsable)

El score es explicable: junto con el número se retorna el desglose de cada
componente para que la UI pueda mostrar el motivo del estado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.models import (
    Assignment,
    Conflict,
    ConflictKind,
    ConflictSeverity,
    LogisticsBlock,
    PlanStatus,
)

# Umbrales para mapear score → estado
THRESHOLD_CALMA = 0.85
THRESHOLD_OCUPADO = 0.6

# Pesos de las 4 componentes
W_CONFLICTS = 0.4
W_ASSIGN_CONFIDENCE = 0.3
W_TRAVEL = 0.2
W_ORPHANS = 0.1


@dataclass
class FeasibilityBreakdown:
    score: float
    status: PlanStatus
    conflicts_component: float
    assignment_component: float
    travel_component: float
    orphan_component: float
    blockers: int
    warnings: int


def _conflicts_component(
    blocks: List[LogisticsBlock], conflicts: List[Conflict]
) -> float:
    if not blocks:
        return 1.0
    total = len(blocks)
    affected = 0
    seen: set = set()
    for c in conflicts:
        if c.severity == ConflictSeverity.INFO:
            continue
        multiplier = 1.0 if c.severity == ConflictSeverity.BLOCKER else 0.5
        for bid in c.block_ids:
            if bid in seen:
                continue
            seen.add(bid)
            affected += multiplier
    return max(0.0, 1.0 - affected / total)


def _assignment_component(assignments: List[Assignment]) -> float:
    if not assignments:
        return 1.0  # nada que asignar → perfecto por definición
    return sum(a.confidence for a in assignments) / len(assignments)


def _travel_component(
    blocks: List[LogisticsBlock], conflicts: List[Conflict]
) -> float:
    if not blocks:
        return 1.0
    travel_conflicts = sum(
        1 for c in conflicts if c.kind == ConflictKind.TRAVEL_INFEASIBLE
    )
    return max(0.0, 1.0 - travel_conflicts / max(1, len(blocks)))


def _orphan_component(blocks: List[LogisticsBlock]) -> float:
    if not blocks:
        return 1.0
    orphans = sum(1 for b in blocks if not b.responsible)
    return max(0.0, 1.0 - orphans / len(blocks))


def feasibility(
    blocks: List[LogisticsBlock],
    conflicts: List[Conflict],
    assignments: List[Assignment],
) -> FeasibilityBreakdown:
    c = _conflicts_component(blocks, conflicts)
    a = _assignment_component(assignments)
    t = _travel_component(blocks, conflicts)
    o = _orphan_component(blocks)

    score = (
        W_CONFLICTS * c
        + W_ASSIGN_CONFIDENCE * a
        + W_TRAVEL * t
        + W_ORPHANS * o
    )
    score = max(0.0, min(1.0, score))

    if score >= THRESHOLD_CALMA:
        status = PlanStatus.CALMA
    elif score >= THRESHOLD_OCUPADO:
        status = PlanStatus.OCUPADO
    else:
        status = PlanStatus.REVISAR

    blockers = sum(1 for x in conflicts if x.severity == ConflictSeverity.BLOCKER)
    warnings = sum(1 for x in conflicts if x.severity == ConflictSeverity.WARNING)

    return FeasibilityBreakdown(
        score=round(score, 3),
        status=status,
        conflicts_component=round(c, 3),
        assignment_component=round(a, 3),
        travel_component=round(t, 3),
        orphan_component=round(o, 3),
        blockers=blockers,
        warnings=warnings,
    )
