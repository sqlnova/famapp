"""Normalización de eventos de calendario a bloques logísticos.

Convierte un `CalendarEvent` (materia prima, ruidosa, a menudo con campos
faltantes) en un `LogisticsBlock` canónico que el resto del motor puede
razonar de forma determinística.

Principios:
- Tolerante a datos incompletos. Nunca falla por falta de campos: propaga
  `confidence < 1.0` y marca `needs_review`.
- Heurísticas en español LATAM (llevar, retirar, dejar, buscar…).
- Sin LLM — las decisiones del planner deben ser reproducibles.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional

from core.models import (
    CalendarEvent,
    KnownPlace,
    LogisticsBlock,
    LogisticsBlockKind,
)

# ── Vocabulario para clasificar el tipo de bloque ─────────────────────────────

_DROP_VERBS = (
    "llevar", "dejar", "acercar", "alcanzar", "salida",
    "salgo con", "salimos con", "llevo", "dejo",
)

_PICKUP_VERBS = (
    "retirar", "buscar", "pasar a buscar", "recoger", "recojo",
    "levantar", "traer", "ir a buscar", "retiro", "busco",
)

_STAY_NOUNS = (
    "clase", "partido", "entrenamiento", "torneo", "acto",
    "reunion", "reunión", "cumple", "cumpleaños",
    "taller", "ensayo",
)

_ERRAND_NOUNS = (
    "supermercado", "super", "farmacia", "banco", "trámite",
    "tramite", "correo", "pago",
)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _norm(text: Optional[str]) -> str:
    return _strip_accents((text or "").lower()).strip()


def classify_kind(title: str, description: Optional[str] = None) -> LogisticsBlockKind:
    """Inferir el tipo de bloque a partir de texto libre."""
    blob = f"{_norm(title)} {_norm(description)}"

    if any(v in blob for v in _PICKUP_VERBS):
        return LogisticsBlockKind.PICKUP
    if any(v in blob for v in _DROP_VERBS):
        return LogisticsBlockKind.DROP
    if any(n in blob for n in _ERRAND_NOUNS):
        return LogisticsBlockKind.ERRAND
    if any(n in blob for n in _STAY_NOUNS):
        return LogisticsBlockKind.STAY
    return LogisticsBlockKind.UNKNOWN


# ── Resolución de lugar ───────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
        prev = curr
    return prev[-1]


def resolve_place(
    raw_location: Optional[str],
    title: str,
    known_places: Iterable[KnownPlace],
) -> Optional[KnownPlace]:
    """Match fuzzy contra la lista de KnownPlace por alias / nombre / tokens.

    Busca pistas en la ubicación explícita del evento primero; si está vacía,
    intenta inferir desde el título. Retorna `None` si no hay match razonable.
    """
    candidates = list(known_places)
    if not candidates:
        return None

    needle_location = _norm(raw_location)
    needle_title = _norm(title)

    def _score(place: KnownPlace, needle: str) -> int:
        if not needle:
            return 10_000
        alias = _norm(place.alias)
        name = _norm(place.name)
        if alias and alias in needle:
            return 0
        if name and name in needle:
            return 0
        # Distancia mínima entre el needle y alias/nombre
        best = min(
            _levenshtein(needle, alias) if alias else 10_000,
            _levenshtein(needle, name) if name else 10_000,
        )
        return best

    best_place: Optional[KnownPlace] = None
    best_score = 10_000

    for needle in (needle_location, needle_title):
        if not needle:
            continue
        for place in candidates:
            s = _score(place, needle)
            if s < best_score:
                best_score = s
                best_place = place

    # Aceptar si match exacto (score=0) o distancia razonable sobre cadena corta
    if best_place is None:
        return None
    # Alias/nombre contenido en needle → seguro
    if best_score == 0:
        return best_place
    # Fuzzy: aceptar sólo si la diferencia es chica respecto del alias
    alias_len = max(1, len(_norm(best_place.alias)))
    if best_score <= max(2, alias_len // 3):
        return best_place
    return None


# ── Extracción de miembros desde texto ────────────────────────────────────────

# Heurística: nombres propios en título del tipo "retirar a Giuseppe del club".
# Se combina con `event.children` (fuente oficial).
_NAME_TOKEN = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})\b")


def _extract_members_from_text(title: str, known_children: Iterable[str]) -> List[str]:
    """Extraer posibles nombres de chicos mencionados en el título."""
    matches = _NAME_TOKEN.findall(title or "")
    found = []
    known = {c.lower(): c for c in known_children}
    for m in matches:
        key = m.lower()
        if key in known and known[key] not in found:
            found.append(known[key])
    return found


# ── Normalización principal ───────────────────────────────────────────────────

def normalize_event(
    event: CalendarEvent,
    known_places: Optional[Iterable[KnownPlace]] = None,
    known_children: Optional[Iterable[str]] = None,
) -> LogisticsBlock:
    """Convertir un CalendarEvent en un LogisticsBlock canónico."""
    known_places = list(known_places or [])
    known_children = list(known_children or [])

    kind = classify_kind(event.title, event.description)

    place = resolve_place(event.location, event.title, known_places)
    location_alias = place.alias if place else None
    location_name = place.name if place else (event.location or None)

    # Miembros: preferir fuente oficial, completar con inferencia desde texto.
    members: List[str] = list(event.children or [])
    for m in _extract_members_from_text(event.title, known_children):
        if m not in members:
            members.append(m)

    # Scoring de confianza — cada campo faltante baja el score
    penalty = 0.0
    missing: List[str] = []
    if kind == LogisticsBlockKind.UNKNOWN:
        penalty += 0.25
        missing.append("kind")
    if not location_alias and not location_name:
        penalty += 0.25
        missing.append("location")
    if not members:
        penalty += 0.15
        missing.append("members")
    if not event.responsible_nickname:
        penalty += 0.15
        missing.append("responsible")

    confidence = max(0.0, 1.0 - penalty)
    needs_review = confidence < 0.7 or kind == LogisticsBlockKind.UNKNOWN

    notes = None
    if missing:
        notes = f"campos incompletos: {', '.join(missing)}"

    return LogisticsBlock(
        kind=kind,
        title=event.title,
        start=event.start,
        end=event.end,
        location_alias=location_alias,
        location_name=location_name,
        members=members,
        responsible=event.responsible_nickname,
        source_event_ids=[event.id] if event.id else [],
        confidence=confidence,
        needs_review=needs_review,
        notes=notes,
    )


def normalize_events(
    events: Iterable[CalendarEvent],
    known_places: Optional[Iterable[KnownPlace]] = None,
    known_children: Optional[Iterable[str]] = None,
) -> List[LogisticsBlock]:
    places = list(known_places or [])
    children = list(known_children or [])
    return [normalize_event(e, places, children) for e in events]
