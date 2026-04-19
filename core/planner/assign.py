"""Asignación óptima de responsables a bloques.

Formulación: matching ponderado en grafo bipartito (bloques × candidatos).
Para cada par (bloque, candidato) se calcula un costo que combina:

- Disponibilidad (ventana horaria del adulto).
- Preferencia histórica (PreferenceProfile).
- Continuidad de cadena (tiempo de traslado desde el bloque previo del mismo
  candidato).
- Balance de carga (penalizar concentrar todo en la misma persona).
- Restricciones duras (no autorizado → costo infinito).

Se resuelve con el algoritmo húngaro en su variante de costo mínimo. Para
N pequeño (familias de ≤ 6 adultos, ≤ 30 bloques/día) es trivial O(n³) y
determinístico — sin dependencias externas.

El asignador NO sobrescribe bloques que ya tienen responsable — respeta lo
que el usuario (o una rutina) ya fijó. Solo completa los vacíos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from core.models import (
    Assignment,
    AvailabilityWindow,
    FamilyMember,
    LogisticsBlock,
    LogisticsBlockKind,
    PreferenceProfile,
    SupportNetworkMember,
)
from core.planner.conflicts import AvailabilityIndex, _default_travel_time, TravelTimeFn

# Costo "infinito" para restricciones duras (licencia, autorización).
HARD_BLOCKED = 1e6


@dataclass
class AssignmentContext:
    """Contexto de entrada al asignador."""
    family: List[FamilyMember]
    support: List[SupportNetworkMember]
    availability: AvailabilityIndex
    preferences: List[PreferenceProfile]
    travel_time_fn: TravelTimeFn = _default_travel_time
    weights: Dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.weights is None:
            self.weights = {
                "availability": 1.5,
                "preference": 1.0,
                "travel": 0.8,
                "load": 0.5,
                "support_penalty": 0.3,  # pequeño sesgo a favor del núcleo
            }


# ── Costo ────────────────────────────────────────────────────────────────────

def _preference_score(
    member: str,
    block: LogisticsBlock,
    prefs: Iterable[PreferenceProfile],
) -> float:
    """Score [0,1] de afinidad histórica. 0.5 neutral si no hay datos."""
    best = 0.5
    best_specificity = -1
    for p in prefs:
        if p.member_nickname != member:
            continue
        # Más específico gana (weekday + place + kind > place + kind > kind > nada)
        specificity = 0
        if p.weekday is not None:
            if p.weekday != block.start.weekday():
                continue
            specificity += 2
        if p.place_alias is not None:
            if p.place_alias != block.location_alias:
                continue
            specificity += 2
        if p.block_kind is not None:
            if p.block_kind != block.kind:
                continue
            specificity += 1
        if p.sample_size < 2:
            continue
        if specificity > best_specificity:
            best = p.score
            best_specificity = specificity
    return best


def _assignment_cost(
    block: LogisticsBlock,
    candidate: str,
    *,
    is_core: bool,
    can_drive: bool,
    allowed_kinds: List[LogisticsBlockKind],
    allowed_children: List[str],
    previous_block: Optional[LogisticsBlock],
    load_so_far: int,
    ctx: AssignmentContext,
) -> float:
    """Costo de asignar `candidate` a `block`. Más bajo = mejor."""
    # Restricciones duras
    requires_drive = block.kind in (
        LogisticsBlockKind.PICKUP,
        LogisticsBlockKind.DROP,
        LogisticsBlockKind.ERRAND,
    )
    if requires_drive and not can_drive:
        return HARD_BLOCKED
    if allowed_kinds and block.kind not in allowed_kinds:
        return HARD_BLOCKED
    if allowed_children:
        if any(c not in allowed_children for c in block.members):
            return HARD_BLOCKED

    cost = 0.0

    # Disponibilidad (hard window): si no hay ninguna ventana que cubra, penaliza
    # fuerte pero no infinito (las ventanas pueden no estar cargadas y no
    # queremos bloquear asignación por falta de datos).
    if ctx.availability.windows:
        if ctx.availability.covers(candidate, block):
            availability_penalty = 0.0
        else:
            availability_penalty = 1.0
    else:
        availability_penalty = 0.3  # incertidumbre sin datos
    cost += ctx.weights["availability"] * availability_penalty

    # Preferencia: cost = (1 - score)
    pref = _preference_score(candidate, block, ctx.preferences)
    cost += ctx.weights["preference"] * (1.0 - pref)

    # Continuidad de cadena: si ya venía de otro bloque, cuánto tarda en llegar
    if previous_block is not None:
        gap_min = (block.start - previous_block.end).total_seconds() / 60.0
        if gap_min < 0:
            return HARD_BLOCKED  # solape imposible
        origin = previous_block.location_alias or previous_block.location_name
        dest = block.location_alias or block.location_name
        travel_min = ctx.travel_time_fn(origin, dest)
        # Penaliza proporcional al déficit de tiempo (0 si sobra).
        deficit = max(0, travel_min - gap_min)
        cost += ctx.weights["travel"] * (deficit / 30.0)  # normalizado a ~media hora

    # Balance de carga: cada bloque previo del día del mismo candidato suma.
    cost += ctx.weights["load"] * (load_so_far * 0.1)

    # Sesgo núcleo vs red de apoyo
    if not is_core:
        cost += ctx.weights["support_penalty"]

    return cost


# ── Algoritmo húngaro (min-cost) ─────────────────────────────────────────────
# Implementación auto-contenida (sin scipy) porque el dominio es chico y
# queremos cero dependencias extra. Basada en la versión O(n³) con
# matriz cuadrada.

def _hungarian(cost: List[List[float]]) -> List[int]:
    """Resuelve asignación mínima. Retorna col asignada por cada fila.

    Requiere matriz cuadrada. Si una fila no tiene opción válida (todo es
    HARD_BLOCKED), igual se asigna pero llamador debe interpretar con HARD_BLOCKED.
    """
    n = len(cost)
    if n == 0:
        return []
    # Padding por si no es cuadrada
    m = max(n, max(len(r) for r in cost))
    big = 10 * HARD_BLOCKED
    matrix = [row[:] + [big] * (m - len(row)) for row in cost]
    while len(matrix) < m:
        matrix.append([big] * m)

    INF = float("inf")
    u = [0.0] * (m + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, m + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = matrix[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    # p[j] = i asignado a columna j (1-indexed). Invertir.
    row_to_col = [-1] * m
    for j in range(1, m + 1):
        if p[j] != 0:
            row_to_col[p[j] - 1] = j - 1
    return row_to_col[:n]


# ── Flujo principal ──────────────────────────────────────────────────────────

def _candidate_info(
    nickname: str,
    family: List[FamilyMember],
    support: List[SupportNetworkMember],
) -> Tuple[bool, bool, List[LogisticsBlockKind], List[str]]:
    """(is_core, can_drive, allowed_kinds, allowed_children) para el candidato."""
    for m in family:
        if m.nickname == nickname:
            return True, True, [], []
    for s in support:
        if s.nickname == nickname:
            return False, s.can_drive, list(s.allowed_kinds), list(s.allowed_children)
    return False, True, [], []


def _reason_for_assignment(
    candidate: str,
    block: LogisticsBlock,
    ctx: AssignmentContext,
    is_core: bool,
) -> Tuple[str, str]:
    """Devuelve (reason_code, explicación en español) para un assignment."""
    pref = _preference_score(candidate, block, ctx.preferences)
    in_window = (
        ctx.availability.covers(candidate, block)
        if ctx.availability.windows
        else None
    )

    parts: List[str] = []
    reason_codes: List[str] = []

    if pref > 0.7:
        parts.append(f"{candidate} suele ocuparse de esto")
        reason_codes.append("preference_strong")
    if in_window is True:
        parts.append("está en ventana disponible")
        reason_codes.append("in_window")
    if not is_core:
        parts.append("apoyo de la red extendida")
        reason_codes.append("support_network")
    if not parts:
        parts.append("menor costo total del día")
        reason_codes.append("cost_min")

    code = "+".join(reason_codes)
    text = f"Asignado a {candidate}: " + ", ".join(parts) + "."
    return code, text


def assign_responsibles(
    blocks: List[LogisticsBlock],
    ctx: AssignmentContext,
) -> Tuple[List[LogisticsBlock], List[Assignment]]:
    """Asignar responsables a los bloques que no lo tienen.

    Retorna `(blocks_with_assignments, assignments)`. Los bloques que ya
    tenían responsable se respetan — sólo se generan `Assignment` para los
    que estaban vacíos.
    """
    # Separar bloques pre-asignados de los que hay que resolver.
    pending_idx = [i for i, b in enumerate(blocks) if not b.responsible]
    if not pending_idx:
        return list(blocks), []

    # Candidatos: adultos del núcleo + red de apoyo autorizada
    core = [m.nickname for m in ctx.family if not m.is_minor]
    support = [s.nickname for s in ctx.support]
    candidates = core + support
    if not candidates:
        return list(blocks), []

    # Ordenar pendientes cronológicamente para que "previous_block" tenga sentido
    pending_idx.sort(key=lambda i: blocks[i].start)
    pending = [blocks[i] for i in pending_idx]

    # Pre-computar info por candidato
    cand_info = {
        c: _candidate_info(c, ctx.family, ctx.support) for c in candidates
    }

    # Matriz: filas = bloques pendientes, columnas = candidatos (replicados
    # para permitir que un mismo candidato tome varios bloques). Replicamos
    # cada candidato `k` veces donde k = cantidad de bloques, así el húngaro
    # puede asignarle hasta `k` bloques.
    n_blocks = len(pending)
    replicas_per_candidate = max(1, (n_blocks + len(candidates) - 1) // len(candidates) + 1)
    expanded_cols = []
    for c in candidates:
        for _ in range(replicas_per_candidate):
            expanded_cols.append(c)

    # Para computar "previous block" necesitamos un primer pase greedy que dé
    # un orden por candidato. Usamos heurística: asignamos costo sin continuidad
    # primero, computamos la matriz completa con continuidad estimada vía el
    # orden cronológico (previous = último bloque ya asignado al candidato en
    # el plan total, incluyendo pre-asignaciones).
    preassigned_by_candidate: Dict[str, List[LogisticsBlock]] = {}
    for b in blocks:
        if b.responsible:
            preassigned_by_candidate.setdefault(b.responsible, []).append(b)
    for lst in preassigned_by_candidate.values():
        lst.sort(key=lambda b: b.start)

    # Construir costos. Para continuidad: el "previous" es el último bloque
    # pre-asignado al candidato cuyo end sea <= start del pending actual.
    def previous_for(candidate: str, block: LogisticsBlock) -> Optional[LogisticsBlock]:
        pre = preassigned_by_candidate.get(candidate, [])
        prev: Optional[LogisticsBlock] = None
        for b in pre:
            if b.end <= block.start:
                prev = b
            else:
                break
        return prev

    load_counter: Dict[str, int] = {
        c: len(preassigned_by_candidate.get(c, [])) for c in candidates
    }

    cost_matrix: List[List[float]] = []
    for block in pending:
        row: List[float] = []
        for c in expanded_cols:
            is_core, can_drive, allowed_k, allowed_ch = cand_info[c]
            row.append(
                _assignment_cost(
                    block,
                    c,
                    is_core=is_core,
                    can_drive=can_drive,
                    allowed_kinds=allowed_k,
                    allowed_children=allowed_ch,
                    previous_block=previous_for(c, block),
                    load_so_far=load_counter[c],
                    ctx=ctx,
                )
            )
        cost_matrix.append(row)

    # Resolver
    if len(cost_matrix[0]) < n_blocks:
        # Raro, pero por seguridad: rellenar con columnas dummy HARD_BLOCKED
        diff = n_blocks - len(cost_matrix[0])
        for row in cost_matrix:
            row.extend([HARD_BLOCKED] * diff)
        expanded_cols.extend(["__unassigned__"] * diff)

    row_to_col = _hungarian(cost_matrix)

    out_blocks = list(blocks)
    assignments: List[Assignment] = []
    for block_pos, col in enumerate(row_to_col):
        if col < 0 or col >= len(expanded_cols):
            continue
        chosen = expanded_cols[col]
        block = pending[block_pos]
        original_idx = pending_idx[block_pos]
        if chosen == "__unassigned__":
            continue
        cost_value = cost_matrix[block_pos][col]
        is_core, _, _, _ = cand_info[chosen]

        # Top-3 alternativas (mirando un candidato por nombre único, no réplicas)
        seen: Dict[str, float] = {}
        for j, c in enumerate(expanded_cols):
            if c == "__unassigned__" or c == chosen:
                continue
            v = cost_matrix[block_pos][j]
            if c not in seen or v < seen[c]:
                seen[c] = v
        alternatives = sorted(seen.items(), key=lambda kv: kv[1])[:3]
        # Convertir costo a "confianza" relativa del primero
        normalized_alts = [(c, max(0.0, 1.0 - min(v, HARD_BLOCKED) / (HARD_BLOCKED / 100))) for c, v in alternatives]

        confidence = max(0.0, 1.0 - min(cost_value, HARD_BLOCKED) / (HARD_BLOCKED / 100))
        confidence = min(1.0, confidence)

        reason_code, explanation = _reason_for_assignment(chosen, block, ctx, is_core)

        assigned_block = block.model_copy(update={"responsible": chosen})
        out_blocks[original_idx] = assigned_block

        assignments.append(
            Assignment(
                block_id=block.id,
                responsible_nickname=chosen,
                confidence=confidence,
                reason_code=reason_code,
                explanation=explanation,
                alternatives=normalized_alts,
            )
        )

        # Actualizar "previous" para el próximo bloque del mismo candidato
        preassigned_by_candidate.setdefault(chosen, []).append(assigned_block)
        preassigned_by_candidate[chosen].sort(key=lambda b: b.start)
        load_counter[chosen] = load_counter.get(chosen, 0) + 1

    return out_blocks, assignments
