"""Fusión inteligente de bloques logísticos.

Regla central: dos bloques son fusionables si ocurren en el mismo lugar, en
una ventana temporal compatible, con el mismo tipo de acción (no se mezcla
"llevar" con "retirar") y con un responsable compatible (si ambos tienen
responsable, debe ser el mismo).

La fusión es transitiva: se agrupan componentes conexos de la relación
`mergeable`.

La salida preserva siempre `source_event_ids` y `merged_from` para que la UI
pueda desplegar el detalle cuando el usuario lo pida.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from core.models import LogisticsBlock, LogisticsBlockKind

# Tolerancia temporal por defecto para considerar dos bloques "simultáneos".
DEFAULT_TIME_TOLERANCE = timedelta(minutes=15)


def _same_location(a: LogisticsBlock, b: LogisticsBlock) -> bool:
    """Dos bloques están en el mismo lugar si coincide alias o nombre."""
    if a.location_alias and b.location_alias:
        return a.location_alias == b.location_alias
    if a.location_name and b.location_name:
        return a.location_name.strip().lower() == b.location_name.strip().lower()
    return False


def _time_compatible(
    a: LogisticsBlock,
    b: LogisticsBlock,
    tolerance: timedelta = DEFAULT_TIME_TOLERANCE,
) -> bool:
    """Solapan en el tiempo o los inicios están dentro de `tolerance`."""
    if a.end <= b.start - tolerance:
        return False
    if b.end <= a.start - tolerance:
        return False
    return abs(a.start - b.start) <= max(
        tolerance, (a.end - a.start), (b.end - b.start)
    )


def _kind_compatible(a: LogisticsBlockKind, b: LogisticsBlockKind) -> bool:
    """No se fusionan acciones opuestas (llevar vs retirar)."""
    if a == b:
        return True
    # UNKNOWN se puede fusionar con cualquier cosa conocida — hereda el tipo.
    if LogisticsBlockKind.UNKNOWN in (a, b):
        return True
    # STAY puede coexistir con PICKUP/DROP si están en el mismo lugar (ej:
    # "clase de inglés" + "retiro del profe"), pero NO se fusionan — se dejan
    # separados porque describen acciones distintas.
    return False


def _responsible_compatible(a: LogisticsBlock, b: LogisticsBlock) -> bool:
    if a.responsible and b.responsible and a.responsible != b.responsible:
        return False
    return True


def mergeable(
    a: LogisticsBlock,
    b: LogisticsBlock,
    tolerance: timedelta = DEFAULT_TIME_TOLERANCE,
) -> bool:
    """Predicado: ¿pueden estos dos bloques colapsar en uno solo?"""
    if a.id == b.id:
        return False
    if not _same_location(a, b):
        return False
    if not _kind_compatible(a.kind, b.kind):
        return False
    if not _responsible_compatible(a, b):
        return False
    if not _time_compatible(a, b, tolerance):
        return False
    return True


# ── Union-Find para agrupar transitivamente ──────────────────────────────────

class _DSU:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _pickup_title(members: List[str], place: Optional[str]) -> str:
    """Generar título en español para un bloque fusionado de pickup."""
    who = _join_members(members)
    if place:
        return f"Retirar {who} de {place}" if who else f"Retirar del {place}"
    return f"Retirar {who}"


def _drop_title(members: List[str], place: Optional[str]) -> str:
    who = _join_members(members)
    if place:
        return f"Llevar {who} a {place}" if who else f"Llevar al {place}"
    return f"Llevar {who}"


def _join_members(members: List[str]) -> str:
    if not members:
        return "a los chicos"
    if len(members) == 1:
        return f"a {members[0]}"
    if len(members) == 2:
        return f"a {members[0]} y {members[1]}"
    return "a los chicos"


def _build_merged_title(blocks: List[LogisticsBlock]) -> str:
    """Construir un título humano para el bloque resultante."""
    if len(blocks) == 1:
        return blocks[0].title

    # Tipo efectivo: ignorar UNKNOWN
    kinds = {b.kind for b in blocks if b.kind != LogisticsBlockKind.UNKNOWN}
    effective_kind = kinds.pop() if len(kinds) == 1 else blocks[0].kind

    # Miembros únicos preservando orden
    members: List[str] = []
    for b in blocks:
        for m in b.members:
            if m not in members:
                members.append(m)

    place = blocks[0].location_name or blocks[0].location_alias

    if effective_kind == LogisticsBlockKind.PICKUP:
        return _pickup_title(members, place)
    if effective_kind == LogisticsBlockKind.DROP:
        return _drop_title(members, place)

    # Fallback: título del primero con nota
    return blocks[0].title


def _merge_group(blocks: List[LogisticsBlock]) -> LogisticsBlock:
    """Fusionar un grupo ya identificado como conexo."""
    if len(blocks) == 1:
        return blocks[0]

    # Ventana: mínimo start / máximo end
    start: datetime = min(b.start for b in blocks)
    end: datetime = max(b.end for b in blocks)

    # Tipo efectivo
    kinds = [b.kind for b in blocks if b.kind != LogisticsBlockKind.UNKNOWN]
    kind = kinds[0] if kinds else LogisticsBlockKind.UNKNOWN

    # Miembros únicos
    members: List[str] = []
    for b in blocks:
        for m in b.members:
            if m not in members:
                members.append(m)

    # Responsable: el único definido (si hay), sino None
    responsibles = {b.responsible for b in blocks if b.responsible}
    responsible = next(iter(responsibles)) if len(responsibles) == 1 else None

    # Source events + merged_from
    source_event_ids: List[str] = []
    for b in blocks:
        for sid in b.source_event_ids:
            if sid not in source_event_ids:
                source_event_ids.append(sid)

    merged_from = [b.id for b in blocks]

    # Lugar: tomar del primero que lo tenga
    location_alias = next((b.location_alias for b in blocks if b.location_alias), None)
    location_name = next((b.location_name for b in blocks if b.location_name), None)

    # Confianza: promedio — la fusión no aumenta la certeza.
    confidence = sum(b.confidence for b in blocks) / len(blocks)

    needs_review = any(b.needs_review for b in blocks)

    title = _build_merged_title(blocks)

    return LogisticsBlock(
        kind=kind,
        title=title,
        start=start,
        end=end,
        location_alias=location_alias,
        location_name=location_name,
        members=members,
        responsible=responsible,
        source_event_ids=source_event_ids,
        merged_from=merged_from,
        confidence=confidence,
        needs_review=needs_review,
        notes=f"fusionado de {len(blocks)} eventos",
    )


def merge_compatible(
    blocks: Iterable[LogisticsBlock],
    tolerance: timedelta = DEFAULT_TIME_TOLERANCE,
) -> List[LogisticsBlock]:
    """Colapsar bloques compatibles preservando el orden cronológico.

    Agrupa por componentes conexos de la relación `mergeable` y produce un
    bloque por grupo. El input no se modifica; la lista devuelta está
    ordenada por `start`.
    """
    items = list(blocks)
    n = len(items)
    if n <= 1:
        return list(items)

    dsu = _DSU(n)
    for i in range(n):
        for j in range(i + 1, n):
            if mergeable(items[i], items[j], tolerance):
                dsu.union(i, j)

    groups: dict[int, List[LogisticsBlock]] = {}
    for idx, block in enumerate(items):
        root = dsu.find(idx)
        groups.setdefault(root, []).append(block)

    merged = [_merge_group(g) for g in groups.values()]
    merged.sort(key=lambda b: b.start)
    return merged
