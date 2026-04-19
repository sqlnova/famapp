"""Agregador de feedback → PreferenceProfile.

La UI emite `plan_feedback` rows cuando el usuario Acepta o Corrige un bloque.
Este módulo toma el corpus de feedback reciente y calcula afinidades
(responsable × lugar × tipo) que el asignador usa como `preferences` en
próximos planes.

Modelo simple:
- Cada fila cuenta como una evidencia para un par (responsable, lugar, kind).
- Acciones ACCEPT suman positivo al responsable asignado.
- Acciones OVERRIDE / EDIT suman positivo al `new_responsible` y negativo al
  `old_responsible`.
- Acciones IGNORE no mueven la aguja.

Score = smoothed ratio (Laplace) entre positivas y totales por par, con
`sample_size` reportado para que el caller decida cuánto confiar.

Sin LLM, determinista, idempotente: re-correr sobre el mismo corpus da el
mismo resultado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from core.models import PlanFeedbackAction, PreferenceProfile


# Clave del par que aprendemos: (responsable, lugar, kind).
# `weekday` se omite del MVP (demanda mucha más masa de datos).
_Key = Tuple[str, Optional[str], Optional[str]]


@dataclass
class _Counter:
    pos: int = 0   # evidencias a favor de este responsable
    neg: int = 0   # evidencias en contra (overrides salientes)


def _classify(row: Dict) -> List[Tuple[_Key, str]]:
    """Retornar (key, signo) a emitir para esta fila de feedback.

    Una fila puede generar 0, 1 o 2 tuplas (OVERRIDE produce + para el nuevo
    y − para el viejo).
    """
    action = (row.get("action") or "").lower()
    place = row.get("place_alias")
    kind = row.get("block_kind")
    old = row.get("old_responsible")
    new = row.get("new_responsible")

    emits: List[Tuple[_Key, str]] = []
    if action == PlanFeedbackAction.ACCEPT.value:
        # En ACCEPT el responsable relevante es el que el planner propuso,
        # que la UI guarda como `new_responsible` (o fallback a old).
        who = new or old
        if who:
            emits.append(((who, place, kind), "+"))
    elif action in (PlanFeedbackAction.OVERRIDE.value, PlanFeedbackAction.EDIT.value):
        if new:
            emits.append(((new, place, kind), "+"))
        if old and old != new:
            emits.append(((old, place, kind), "-"))
    # IGNORE: sin efecto.
    return emits


def _smoothed_score(pos: int, neg: int, alpha: float = 1.0) -> float:
    """Laplace-smoothed proporción a favor.

    Con 0 evidencias devuelve 0.5 (neutral). Con mucha masa tiende al ratio
    empírico. `alpha=1` es el prior clásico add-one.
    """
    total = pos + neg
    return (pos + alpha) / (total + 2 * alpha)


def aggregate_preferences(
    feedback_rows: Iterable[Dict],
    *,
    min_sample_size: int = 2,
) -> List[PreferenceProfile]:
    """Compactar feedback crudo en una lista de `PreferenceProfile`.

    Args:
        feedback_rows: filas tal cual salen de `plan_feedback` en Supabase
            (dicts con action / old_responsible / new_responsible /
            place_alias / block_kind).
        min_sample_size: umbral mínimo (pos+neg) para emitir un perfil. Por
            debajo del umbral no hay masa suficiente; se omite.

    Returns:
        Lista de perfiles listos para persistir con
        `upsert_preference_profile`. Uno por par (responsable, lugar, kind).
    """
    counters: Dict[_Key, _Counter] = {}
    for row in feedback_rows:
        for key, sign in _classify(row):
            c = counters.setdefault(key, _Counter())
            if sign == "+":
                c.pos += 1
            else:
                c.neg += 1

    profiles: List[PreferenceProfile] = []
    for (member, place, kind), c in counters.items():
        total = c.pos + c.neg
        if total < min_sample_size:
            continue
        profiles.append(PreferenceProfile(
            member_nickname=member,
            place_alias=place,
            block_kind=kind,
            weekday=None,
            score=_smoothed_score(c.pos, c.neg),
            sample_size=total,
        ))
    # Determinismo: orden estable por (member, place, kind).
    profiles.sort(key=lambda p: (
        p.member_nickname,
        p.place_alias or "",
        (p.block_kind.value if p.block_kind else ""),
    ))
    return profiles
