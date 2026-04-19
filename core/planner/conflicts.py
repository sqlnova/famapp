"""Detección de conflictos en un plan logístico.

Modela el plan como grafo de recursos: cada bloque consume
(responsable × tiempo × lugar). Los conflictos son violaciones detectables
de ese grafo.

Tipos detectados:
- TEMPORAL_PERSON: un mismo responsable asignado a dos bloques solapados.
- SPATIAL: bloques simultáneos en lugares distintos cuando no hay adultos
  suficientes disponibles para cubrirlos.
- TRAVEL_INFEASIBLE: el mismo responsable tiene bloques consecutivos pero
  el tiempo de traslado entre lugares supera el hueco disponible.
- ORPHAN_MINOR: un menor queda en un bloque sin adulto responsable o sin
  alguien de la red de apoyo autorizado.
- DRIVER: el responsable no está autorizado / no puede cubrir ese tipo.

El módulo es puro: no toca DB, no hace llamadas externas. Si hace falta
información de traslado, se recibe como callable inyectable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core.models import (
    AvailabilityWindow,
    Conflict,
    ConflictKind,
    ConflictSeverity,
    FamilyMember,
    LogisticsBlock,
    LogisticsBlockKind,
    SupportNetworkMember,
)

# Tiempo por defecto asumido para un traslado intra-ciudad cuando no hay
# información real. Realista para capitales LATAM de tamaño medio.
DEFAULT_TRAVEL_MINUTES = 20

# Tiempo de estimación cuando los bloques están en el mismo lugar.
SAME_PLACE_TRAVEL_MINUTES = 0


TravelTimeFn = Callable[[Optional[str], Optional[str]], int]


def _default_travel_time(origin: Optional[str], destination: Optional[str]) -> int:
    """Fallback determinístico: 0 si mismo lugar, DEFAULT si distinto."""
    if not origin or not destination:
        return DEFAULT_TRAVEL_MINUTES
    if origin.strip().lower() == destination.strip().lower():
        return SAME_PLACE_TRAVEL_MINUTES
    return DEFAULT_TRAVEL_MINUTES


# ── Índice de disponibilidad ─────────────────────────────────────────────────

@dataclass
class AvailabilityIndex:
    """Helper para consultar ventanas de disponibilidad rápido."""

    windows: List[AvailabilityWindow] = field(default_factory=list)

    def covers(self, member: str, block: LogisticsBlock) -> bool:
        """¿El miembro tiene alguna ventana que cubra el bloque entero?"""
        weekday = block.start.weekday()
        for w in self.windows:
            if w.member_nickname != member:
                continue
            if w.weekday != weekday:
                continue
            if w.start <= block.start.time() and block.end.time() <= w.end:
                return True
        return False

    def any_covers(self, members: Iterable[str], block: LogisticsBlock) -> List[str]:
        """Lista de miembros (del input) que tienen disponibilidad para el bloque."""
        return [m for m in members if self.covers(m, block)]


# ── Detectores individuales ──────────────────────────────────────────────────

def _location_key(block: LogisticsBlock) -> Optional[str]:
    return block.location_alias or block.location_name


def _overlaps(a: LogisticsBlock, b: LogisticsBlock) -> bool:
    return a.start < b.end and b.start < a.end


def detect_temporal_person(blocks: List[LogisticsBlock]) -> List[Conflict]:
    """Mismo responsable en dos bloques que solapan en el tiempo."""
    conflicts: List[Conflict] = []
    n = len(blocks)
    for i in range(n):
        a = blocks[i]
        if not a.responsible:
            continue
        for j in range(i + 1, n):
            b = blocks[j]
            if a.responsible != b.responsible:
                continue
            if not _overlaps(a, b):
                continue
            conflicts.append(
                Conflict(
                    kind=ConflictKind.TEMPORAL_PERSON,
                    severity=ConflictSeverity.BLOCKER,
                    block_ids=[a.id, b.id],
                    involved_members=[a.responsible],
                    reason_code="same_responsible_overlap",
                    explanation=(
                        f"{a.responsible} está asignado a dos cosas al mismo tiempo: "
                        f"«{a.title}» y «{b.title}»."
                    ),
                    suggested_resolutions=[
                        "Reasignar uno de los dos bloques a otro adulto disponible.",
                        "Pedir apoyo a la red (abuelos / vecino / carpool).",
                    ],
                )
            )
    return conflicts


def detect_spatial(
    blocks: List[LogisticsBlock],
    adults_pool: List[str],
    availability: AvailabilityIndex,
) -> List[Conflict]:
    """Bloques simultáneos en lugares distintos sin adultos suficientes.

    No todos los solapes son conflicto: si los bloques son en el mismo lugar,
    los cubre la fase de fusión previa. Acá detectamos cuando la cantidad de
    *lugares distintos simultáneos* supera la cantidad de adultos disponibles
    para ese momento.
    """
    conflicts: List[Conflict] = []
    n = len(blocks)
    seen_groups: List[Tuple[int, ...]] = []

    for i in range(n):
        # Buscar el "cluster" de bloques que solapan con i (sólo hacia adelante
        # para evitar duplicados de grupos).
        cluster_idx = [i]
        for j in range(i + 1, n):
            if all(_overlaps(blocks[k], blocks[j]) for k in cluster_idx):
                cluster_idx.append(j)
        if len(cluster_idx) < 2:
            continue

        # Dedupe por contenido del grupo
        key = tuple(cluster_idx)
        if key in seen_groups:
            continue
        seen_groups.append(key)

        cluster = [blocks[k] for k in cluster_idx]
        locations = {_location_key(b) for b in cluster if _location_key(b)}
        if len(locations) < 2:
            continue  # misma ubicación → lo resuelve merge

        # ¿Cuántos adultos del pool tienen disponibilidad en esa ventana?
        covering: set[str] = set()
        for b in cluster:
            for m in availability.any_covers(adults_pool, b):
                covering.add(m)

        available_count = len(covering) if covering else len(adults_pool)

        if available_count < len(locations):
            conflicts.append(
                Conflict(
                    kind=ConflictKind.SPATIAL,
                    severity=ConflictSeverity.BLOCKER,
                    block_ids=[b.id for b in cluster],
                    involved_members=list(covering or adults_pool),
                    reason_code="not_enough_adults_for_locations",
                    explanation=(
                        f"Hay {len(locations)} compromisos simultáneos en lugares "
                        f"distintos y solo {available_count} adultos disponibles."
                    ),
                    suggested_resolutions=[
                        "Pedir apoyo a la red (abuelos / vecino / carpool).",
                        "Reagendar alguno de los compromisos.",
                        "Evaluar si alguno puede adelantarse o atrasarse.",
                    ],
                )
            )
    return conflicts


def detect_travel_infeasible(
    blocks: List[LogisticsBlock],
    travel_time_fn: TravelTimeFn = _default_travel_time,
) -> List[Conflict]:
    """Mismo responsable con bloques consecutivos y tiempo de viaje > hueco."""
    conflicts: List[Conflict] = []

    # Agrupar por responsable y ordenar cronológicamente
    by_responsible: Dict[str, List[LogisticsBlock]] = {}
    for b in blocks:
        if not b.responsible:
            continue
        by_responsible.setdefault(b.responsible, []).append(b)

    for responsible, items in by_responsible.items():
        items.sort(key=lambda b: b.start)
        for prev, nxt in zip(items, items[1:]):
            gap_min = (nxt.start - prev.end).total_seconds() / 60.0
            if gap_min < 0:
                continue  # solape real: lo detecta temporal_person
            origin = _location_key(prev)
            dest = _location_key(nxt)
            travel_min = travel_time_fn(origin, dest)
            if travel_min > gap_min:
                conflicts.append(
                    Conflict(
                        kind=ConflictKind.TRAVEL_INFEASIBLE,
                        severity=ConflictSeverity.WARNING,
                        block_ids=[prev.id, nxt.id],
                        involved_members=[responsible],
                        reason_code="travel_exceeds_gap",
                        explanation=(
                            f"{responsible} tiene {int(gap_min)} min entre «{prev.title}» "
                            f"y «{nxt.title}», pero el traslado estimado es de "
                            f"{travel_min} min."
                        ),
                        suggested_resolutions=[
                            "Adelantar la salida del primer bloque.",
                            "Reasignar uno de los dos a otro adulto.",
                            "Pedir que alguien más lleve / retire.",
                        ],
                    )
                )
    return conflicts


def detect_driver_unauthorized(
    blocks: List[LogisticsBlock],
    family: Iterable[FamilyMember],
    support: Iterable[SupportNetworkMember],
) -> List[Conflict]:
    """El responsable asignado no puede cubrir ese tipo de tarea."""
    conflicts: List[Conflict] = []
    core_members = {m.nickname for m in family if not m.is_minor}
    support_by_nick: Dict[str, SupportNetworkMember] = {
        s.nickname: s for s in support
    }

    for block in blocks:
        if not block.responsible:
            continue
        if block.responsible in core_members:
            continue
        # Si no es del núcleo, debe estar en la red de apoyo y estar autorizado
        s = support_by_nick.get(block.responsible)
        if s is None:
            conflicts.append(
                Conflict(
                    kind=ConflictKind.DRIVER,
                    severity=ConflictSeverity.BLOCKER,
                    block_ids=[block.id],
                    involved_members=[block.responsible],
                    reason_code="unknown_responsible",
                    explanation=(
                        f"«{block.responsible}» no está en la familia ni en la "
                        f"red de apoyo."
                    ),
                    suggested_resolutions=["Reasignar a un adulto conocido."],
                )
            )
            continue

        requires_drive = block.kind in (
            LogisticsBlockKind.PICKUP,
            LogisticsBlockKind.DROP,
            LogisticsBlockKind.ERRAND,
        )
        if requires_drive and not s.can_drive:
            conflicts.append(
                Conflict(
                    kind=ConflictKind.DRIVER,
                    severity=ConflictSeverity.BLOCKER,
                    block_ids=[block.id],
                    involved_members=[block.responsible],
                    reason_code="cannot_drive",
                    explanation=(
                        f"{s.name} no maneja y este bloque requiere traslado."
                    ),
                    suggested_resolutions=[
                        "Reasignar a un adulto que maneje.",
                        "Combinar con otro traslado cercano.",
                    ],
                )
            )

        if s.allowed_kinds and block.kind not in s.allowed_kinds:
            conflicts.append(
                Conflict(
                    kind=ConflictKind.DRIVER,
                    severity=ConflictSeverity.WARNING,
                    block_ids=[block.id],
                    involved_members=[block.responsible],
                    reason_code="kind_not_allowed",
                    explanation=(
                        f"{s.name} no suele cubrir este tipo de tarea "
                        f"({block.kind.value})."
                    ),
                    suggested_resolutions=[
                        "Confirmar con la familia si hoy puede hacerlo.",
                    ],
                )
            )

        if s.allowed_children:
            unauthorized = [
                c for c in block.members if c not in s.allowed_children
            ]
            if unauthorized:
                conflicts.append(
                    Conflict(
                        kind=ConflictKind.DRIVER,
                        severity=ConflictSeverity.WARNING,
                        block_ids=[block.id],
                        involved_members=[block.responsible],
                        reason_code="child_not_allowed",
                        explanation=(
                            f"{s.name} no está autorizado para "
                            f"{', '.join(unauthorized)}."
                        ),
                        suggested_resolutions=[
                            "Confirmar con el adulto a cargo del menor.",
                        ],
                    )
                )
    return conflicts


def detect_orphan_minor(
    blocks: List[LogisticsBlock],
    family: Iterable[FamilyMember],
) -> List[Conflict]:
    """Menor involucrado en un bloque sin responsable adulto asignado.

    Este es el conflicto más silencioso — solo aparece cuando hay chicos
    pero el bloque no tiene responsable tras la asignación.
    """
    conflicts: List[Conflict] = []
    minors = {m.nickname for m in family if m.is_minor}
    minor_names_lower = {m.name.lower() for m in family if m.is_minor}

    for block in blocks:
        if block.kind == LogisticsBlockKind.STAY:
            # STAY no requiere adulto presente siempre (clase, partido)
            continue
        if not block.members:
            continue
        involves_minor = any(
            m.lower() in minor_names_lower or m in minors for m in block.members
        )
        if not involves_minor:
            continue
        if block.responsible:
            continue
        conflicts.append(
            Conflict(
                kind=ConflictKind.ORPHAN_MINOR,
                severity=ConflictSeverity.BLOCKER,
                block_ids=[block.id],
                involved_members=list(block.members),
                reason_code="minor_without_adult",
                explanation=(
                    f"«{block.title}» involucra a {', '.join(block.members)} "
                    f"pero no tiene adulto responsable."
                ),
                suggested_resolutions=[
                    "Asignar un adulto del núcleo.",
                    "Delegar en la red de apoyo.",
                ],
            )
        )
    return conflicts


# ── Orquestador ──────────────────────────────────────────────────────────────

def detect_conflicts(
    blocks: List[LogisticsBlock],
    *,
    family: Optional[Iterable[FamilyMember]] = None,
    support: Optional[Iterable[SupportNetworkMember]] = None,
    availability: Optional[AvailabilityIndex] = None,
    travel_time_fn: TravelTimeFn = _default_travel_time,
) -> List[Conflict]:
    """Correr todos los detectores y retornar la lista consolidada.

    Cada detector es independiente — un mismo par de bloques puede aparecer en
    más de un conflicto (ej: temporal_person + travel_infeasible se excluyen
    entre sí por construcción, pero orphan_minor + driver pueden coexistir).
    """
    family = list(family or [])
    support = list(support or [])
    availability = availability or AvailabilityIndex()
    adults_pool = [m.nickname for m in family if not m.is_minor]

    out: List[Conflict] = []
    out.extend(detect_temporal_person(blocks))
    out.extend(detect_spatial(blocks, adults_pool, availability))
    out.extend(detect_travel_infeasible(blocks, travel_time_fn))
    if family or support:
        out.extend(detect_driver_unauthorized(blocks, family, support))
    if family:
        out.extend(detect_orphan_minor(blocks, family))
    return out
