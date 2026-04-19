"""Motor de planificación logística de Famapp.

Pipeline diario:

    events → normalize → merge → (conflict → assign → score)

Este paquete expone primero `normalize` y `merge`. Las etapas de detección
de conflictos, asignación y scoring se agregan en fases posteriores.
"""
from __future__ import annotations

from core.planner.merge import merge_compatible
from core.planner.normalize import normalize_event, normalize_events

__all__ = ["normalize_event", "normalize_events", "merge_compatible"]
