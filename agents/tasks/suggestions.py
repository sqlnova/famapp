"""Task suggestion engine based on event patterns."""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re

from core.models import CalendarEvent


def calculate_task_due_date(event: CalendarEvent, task_type: str) -> Optional[str]:
    """Calculate intelligent due date for a task based on event type and timing.

    Args:
        event: The calendar event
        task_type: Type of task (e.g., "comprar", "preparar", "confirmar")

    Returns:
        ISO date string for task due date, or None
    """
    if not event.start or not event.start.tzinfo:
        return None

    event_date = event.start.astimezone(event.start.tzinfo)
    task_title_lower = task_type.lower()

    # Travel-related tasks: due 2 days before
    if any(w in task_title_lower for w in ["preparar maleta", "confirmar vuelo", "revisar pasaportes"]):
        due = event_date - timedelta(days=2)
        return due.date().isoformat()

    # Shopping tasks: due 1 day before
    if any(w in task_title_lower for w in ["comprar", "regalo"]):
        due = event_date - timedelta(days=1)
        return due.date().isoformat()

    # Preparation tasks: due 1 day before
    if any(w in task_title_lower for w in ["preparar", "decoración", "organizar comida"]):
        due = event_date - timedelta(days=1)
        return due.date().isoformat()

    # Confirmation tasks: due 3 days before
    if any(w in task_title_lower for w in ["confirmar turno", "confirmar asistencia"]):
        due = event_date - timedelta(days=3)
        return due.date().isoformat()

    return None


def generate_task_suggestions(event: CalendarEvent) -> List[Dict[str, Any]]:
    """Generate task suggestions based on event characteristics.

    Args:
        event: The calendar event to analyze

    Returns:
        List of suggested tasks with title, description, and metadata
    """
    suggestions = []
    title_lower = (event.title or "").lower()
    location_lower = (event.location or "").lower()

    # Pattern: Birthday/Cumpleaños
    if any(w in title_lower for w in ["cumpleaños", "birthday", "cumple"]):
        suggestions.extend([
            {
                "title": "Comprar regalo",
                "description": f"Regalo para {event.title}",
                "due_date": calculate_task_due_date(event, "comprar regalo"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Preparar decoración",
                "description": "Globos, guirnaldas, etc.",
                "due_date": calculate_task_due_date(event, "decoración"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Organizar comida/bebidas",
                "description": "Torta, snacks, bebidas",
                "due_date": calculate_task_due_date(event, "organizar comida"),
                "assignee": event.responsible_nickname
            },
        ])

    # Pattern: Travel/Viaje
    if any(w in title_lower for w in ["aeropuerto", "terminal", "viaje", "vuelo", "colectivo", "tren", "trip", "airport"]):
        days_until = (event.start - datetime.now(event.start.tzinfo)).days if event.start.tzinfo else 0
        suggestions.extend([
            {
                "title": "Preparar maleta",
                "description": "Ropa, documentos, etc.",
                "due_date": calculate_task_due_date(event, "preparar maleta"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Confirmar vuelo/pasaje",
                "description": "Revisar reserva y horarios",
                "due_date": calculate_task_due_date(event, "confirmar vuelo"),
                "assignee": event.responsible_nickname
            },
        ])
        if days_until > 1:
            suggestions.append({
                "title": "Revisar pasaportes",
                "description": "Asegurar que estén vigentes",
                "due_date": calculate_task_due_date(event, "revisar pasaportes"),
                "assignee": event.responsible_nickname
            })

    # Pattern: Medical appointment/Cita médica
    if any(w in title_lower for w in ["médico", "doctor", "dentista", "pediatra", "dentist", "médica", "hospital", "clínica"]):
        suggestions.extend([
            {
                "title": "Confirmar turno",
                "description": f"Llamar para confirmar {event.title}",
                "due_date": calculate_task_due_date(event, "confirmar turno"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Preparar documentos médicos",
                "description": "Carnet, historia clínica",
                "due_date": calculate_task_due_date(event, "preparar"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Preparar lista de preguntas",
                "description": "Síntomas, dudas para el doctor",
                "due_date": calculate_task_due_date(event, "preparar"),
                "assignee": event.responsible_nickname
            },
        ])

    # Pattern: School/Activity
    if any(w in title_lower for w in ["colegio", "escuela", "school", "guardería", "jardín", "gym", "fútbol", "tenis", "natación"]):
        if "llevar" in title_lower or "buscar" not in title_lower:
            suggestions.append({
                "title": "Preparar mochila",
                "description": f"Uniforme, útiles para {event.title}",
                "due_date": calculate_task_due_date(event, "preparar"),
                "assignee": event.responsible_nickname
            })

    # Pattern: Meeting/Reunión
    if any(w in title_lower for w in ["reunión", "meeting", "junta", "conferencia"]):
        suggestions.append({
            "title": "Preparar documentos",
            "description": "Revisar agenda y preparar material",
            "due_date": calculate_task_due_date(event, "preparar"),
            "assignee": event.responsible_nickname
        })

    # Pattern: Party/Evento social
    if any(w in title_lower for w in ["fiesta", "party", "celebración", "evento", "cena", "almuerzo"]):
        suggestions.extend([
            {
                "title": "Confirmar asistencia",
                "description": f"Confirmar para {event.title}",
                "due_date": calculate_task_due_date(event, "confirmar asistencia"),
                "assignee": event.responsible_nickname
            },
            {
                "title": "Preparar regalo/detalles",
                "description": "Si aplica",
                "due_date": calculate_task_due_date(event, "comprar regalo"),
                "assignee": event.responsible_nickname
            },
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

