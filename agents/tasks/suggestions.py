"""Task suggestion engine based on event patterns."""
from typing import List, Dict, Any, Optional
from datetime import datetime
import re

from core.models import CalendarEvent


def generate_task_suggestions(event: CalendarEvent) -> List[Dict[str, Any]]:
    """Generate task suggestions based on event characteristics.

    Args:
        event: The calendar event to analyze

    Returns:
        List of suggested tasks with title and description
    """
    suggestions = []
    title_lower = (event.title or "").lower()
    location_lower = (event.location or "").lower()

    # Pattern: Birthday/Cumpleaños
    if any(w in title_lower for w in ["cumpleaños", "birthday", "cumple"]):
        suggestions.extend([
            {"title": "Comprar regalo", "description": f"Regalo para {event.title}"},
            {"title": "Preparar decoración", "description": "Globos, guirnaldas, etc."},
            {"title": "Organizar comida/bebidas", "description": "Torta, snacks, bebidas"},
        ])

    # Pattern: Travel/Viaje
    if any(w in title_lower for w in ["aeropuerto", "terminal", "viaje", "vuelo", "colectivo", "tren", "trip", "airport"]):
        days_until = (event.start - datetime.now(event.start.tzinfo)).days if event.start.tzinfo else 0
        suggestions.extend([
            {"title": "Preparar maleta", "description": "Ropa, documentos, etc."},
            {"title": "Confirmar vuelo/pasaje", "description": "Revisar reserva y horarios"},
        ])
        if days_until > 1:
            suggestions.append(
                {"title": "Revisar pasaportes", "description": "Asegurar que estén vigentes"}
            )

    # Pattern: Medical appointment/Cita médica
    if any(w in title_lower for w in ["médico", "doctor", "dentista", "pediatra", "dentist", "médica", "hospital", "clínica"]):
        suggestions.extend([
            {"title": "Confirmar turno", "description": f"Llamar para confirmar {event.title}"},
            {"title": "Preparar documentos médicos", "description": "Carnet, historia clínica"},
            {"title": "Preparar lista de preguntas", "description": "Síntomas, dudas para el doctor"},
        ])

    # Pattern: School/Activity
    if any(w in title_lower for w in ["colegio", "escuela", "school", "guardería", "jardín", "gym", "fútbol", "tenis", "natación"]):
        if "llevar" in title_lower or "buscar" not in title_lower:
            suggestions.append(
                {"title": "Preparar mochila", "description": f"Uniforme, útiles para {event.title}"}
            )

    # Pattern: Meeting/Reunión
    if any(w in title_lower for w in ["reunión", "meeting", "junta", "conferencia"]):
        suggestions.append(
            {"title": "Preparar documentos", "description": "Revisar agenda y preparar material"}
        )

    # Pattern: Party/Evento social
    if any(w in title_lower for w in ["fiesta", "party", "celebración", "evento", "cena", "almuerzo"]):
        suggestions.extend([
            {"title": "Confirmar asistencia", "description": f"Confirmar para {event.title}"},
            {"title": "Preparar regalo/detalles", "description": "Si aplica"},
        ])

    return suggestions


def filter_duplicate_suggestions(suggestions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate suggestions by title."""
    seen = set()
    unique = []
    for s in suggestions:
        title = s["title"].lower()
        if title not in seen:
            seen.add(title)
            unique.append(s)
    return unique
