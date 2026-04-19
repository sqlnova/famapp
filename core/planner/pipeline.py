"""Pipeline diario del copiloto logístico.

Orquesta las 5 etapas en una sola función `plan_day`:

    events → normalize → merge → conflicts → assign → feasibility

Todas las etapas son deterministas. Sin LLM. Tolerante a datos incompletos.
Si falta información clave, el plan se genera igual con `confidence < 1.0` y
se marcan los bloques que requieren revisión.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from core.models import (
    CalendarEvent,
    DailyPlan,
    FamilyMember,
    KnownPlace,
    LogisticsBlock,
    PreferenceProfile,
    SupportNetworkMember,
    Trip,
)
from core.planner.assign import AssignmentContext, assign_responsibles
from core.planner.conflicts import (
    AvailabilityIndex,
    TravelTimeFn,
    _default_travel_time,
    detect_conflicts,
)
from core.planner.feasibility import feasibility
from core.planner.merge import merge_compatible
from core.planner.normalize import normalize_events


@dataclass
class FamilyContext:
    """Contexto de la familia — todo lo que el planner necesita saber."""
    family: List[FamilyMember] = field(default_factory=list)
    support: List[SupportNetworkMember] = field(default_factory=list)
    known_places: List[KnownPlace] = field(default_factory=list)
    availability: AvailabilityIndex = field(default_factory=AvailabilityIndex)
    preferences: List[PreferenceProfile] = field(default_factory=list)
    travel_time_fn: TravelTimeFn = _default_travel_time

    @property
    def known_children(self) -> List[str]:
        return [m.name for m in self.family if m.is_minor]


def _build_trips(blocks: List[LogisticsBlock]) -> List[Trip]:
    """Construir un Trip por cada bloque que implique traslado.

    STAY no genera trip. PICKUP y DROP sí. Múltiples bloques del mismo
    responsable en el mismo lugar y ventana ya están fusionados antes.
    """
    from core.models import LogisticsBlockKind

    trips: List[Trip] = []
    for block in blocks:
        if block.kind == LogisticsBlockKind.STAY:
            continue
        destination = block.location_name or block.location_alias or "destino desconocido"
        trip = Trip(
            origin=None,
            destination=destination,
            depart_at=block.start,
            arrive_at=block.end,
            driver_nickname=block.responsible,
            passenger_members=list(block.members),
            block_ids=[block.id],
            combined=len(block.merged_from) > 1,
        )
        trips.append(trip)
    return trips


def _build_summary_es(
    blocks: List[LogisticsBlock],
    conflicts_count: int,
    combined_count: int,
    status_label: str,
) -> str:
    """Resumen corto en español para la UI."""
    total = len(blocks)
    pieces = [f"{total} bloques · estado {status_label}"]
    if combined_count:
        pieces.append(f"{combined_count} traslados combinados")
    if conflicts_count:
        pieces.append(f"{conflicts_count} conflictos")
    return " · ".join(pieces)


def plan_day(
    date: str,
    events: Iterable[CalendarEvent],
    ctx: Optional[FamilyContext] = None,
) -> DailyPlan:
    """Generar el plan del día.

    Args:
        date: YYYY-MM-DD del día a planificar.
        events: eventos crudos del calendario (incluir expansión de rutinas).
        ctx: contexto familiar. Si es None se usa uno vacío — el plan se
             genera igual pero con baja confianza y muchos campos vacíos.

    Returns:
        `DailyPlan` listo para serializar o renderizar.
    """
    ctx = ctx or FamilyContext()

    # 1. Normalizar eventos → bloques canónicos
    blocks = normalize_events(
        events,
        known_places=ctx.known_places,
        known_children=ctx.known_children,
    )

    # 2. Fusionar bloques compatibles (mismo lugar, ventana, kind, responsable)
    merged_blocks = merge_compatible(blocks)

    # 3. Asignar responsables a los bloques que no lo tienen
    assign_ctx = AssignmentContext(
        family=ctx.family,
        support=ctx.support,
        availability=ctx.availability,
        preferences=ctx.preferences,
        travel_time_fn=ctx.travel_time_fn,
    )
    assigned_blocks, assignments = assign_responsibles(merged_blocks, assign_ctx)

    # 4. Detectar conflictos sobre el plan ya asignado
    conflicts = detect_conflicts(
        assigned_blocks,
        family=ctx.family,
        support=ctx.support,
        availability=ctx.availability,
        travel_time_fn=ctx.travel_time_fn,
    )

    # 5. Construir traslados físicos
    trips = _build_trips(assigned_blocks)
    combined_count = sum(1 for t in trips if t.combined)

    # 6. Score de factibilidad y estado
    fb = feasibility(assigned_blocks, conflicts, assignments)

    summary_es = _build_summary_es(
        assigned_blocks, len(conflicts), combined_count, fb.status.value
    )

    return DailyPlan(
        date=date,
        status=fb.status,
        feasibility_score=fb.score,
        blocks=assigned_blocks,
        trips=trips,
        conflicts=conflicts,
        assignments=assignments,
        summary_es=summary_es,
    )
