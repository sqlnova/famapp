"""Motor de planificación logística de Famapp.

Pipeline diario:

    events → normalize → merge → conflicts → assign → feasibility
"""
from __future__ import annotations

from core.planner.assign import AssignmentContext, assign_responsibles
from core.planner.conflicts import (
    AvailabilityIndex,
    detect_conflicts,
    detect_driver_unauthorized,
    detect_orphan_minor,
    detect_spatial,
    detect_temporal_person,
    detect_travel_infeasible,
)
from core.planner.feasibility import FeasibilityBreakdown, feasibility
from core.planner.merge import merge_compatible
from core.planner.normalize import normalize_event, normalize_events
from core.planner.pipeline import FamilyContext, plan_day
from core.planner.routines import expand_routines_for_day

__all__ = [
    "normalize_event",
    "normalize_events",
    "merge_compatible",
    "AvailabilityIndex",
    "detect_conflicts",
    "detect_temporal_person",
    "detect_spatial",
    "detect_travel_infeasible",
    "detect_driver_unauthorized",
    "detect_orphan_minor",
    "AssignmentContext",
    "assign_responsibles",
    "feasibility",
    "FeasibilityBreakdown",
    "FamilyContext",
    "plan_day",
    "expand_routines_for_day",
]
