"""Schedule Agent – LangGraph nodes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytz
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.schedule.calendar_client import (
    AR_TZ,
    create_event,
    format_events_for_whatsapp,
    list_upcoming_events,
)
from core.config import get_settings
from core.models import CalendarEvent

logger = structlog.get_logger(__name__)

SCHEDULE_SYSTEM_PROMPT = """Sos el agente de calendario de FamApp.
Recibís un mensaje del usuario junto con las entidades ya extraídas por el Intake Agent.

Tu tarea es determinar si el usuario quiere:
- "list"             : consultar próximos eventos (ej. "¿qué tengo mañana?")
- "create"           : crear un nuevo evento único
- "recurring_create" : crear un evento recurrente (horario escolar, clase semanal, etc.)

Para "create", completá el evento con los datos disponibles:
- Si falta la hora, usá 09:00 como default.
- Si falta la duración, usá 1 hora.
- Las fechas relativas (mañana, próximo lunes, etc.) calcularlas desde hoy: {today}
- Los horarios son siempre en zona horaria Argentina (UTC-3)

Para "recurring_create", el usuario quiere cargar un horario que se repite semanalmente:
- "start_date" : primera fecha de la primera ocurrencia (YYYY-MM-DD)
- "until_date" : fecha hasta la que se repite (YYYY-MM-DD) — default fin del año actual
- "days_of_week": lista de códigos RFC 5545 — MO, TU, WE, TH, FR, SA, SU
- "start_time" : hora de inicio HH:MM
- "end_time"   : hora de fin HH:MM (null → 1 hora después)
- Ejemplos de trigger: "horario del colegio", "clases de natación", "reunion semanal"

Campo "responsible" (aplica a create y recurring_create):
- Extraé el apodo/nombre en minúsculas de quien está a cargo del evento.
- Ejemplos: "el papá lleva" → "papa" / "yo los busco" → "mama" / "llevo yo" → "mama"
- Si no se menciona responsable, dejá null.
- Usá siempre minúsculas sin tildes: "papa", "mama", "sofia", etc.

Respondé SIEMPRE en JSON sin markdown:
{{
  "action": "list" | "create" | "recurring_create",
  "event": {{
    "title": str,
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "duration_minutes": int,
    "location": str | null,
    "responsible": str | null,
    "start_date": "YYYY-MM-DD",
    "until_date": "YYYY-MM-DD",
    "days_of_week": ["MO", "TU", ...],
    "start_time": "HH:MM",
    "end_time": "HH:MM" | null
  }},
  "days_ahead": int
}}
"""


def _get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0)


async def plan_action(raw_text: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Ask LLM to decide list vs create vs recurring_create and fill in event details."""
    llm = _get_llm()
    today = datetime.now(AR_TZ).strftime("%Y-%m-%d (%A)")

    messages = [
        SystemMessage(content=SCHEDULE_SYSTEM_PROMPT.format(today=today)),
        HumanMessage(content=f"Mensaje: {raw_text}\nEntidades: {json.dumps(entities, ensure_ascii=False)}"),
    ]
    response = await llm.ainvoke(messages)
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", response.content, re.DOTALL)
        return json.loads(match.group()) if match else {"action": "list", "days_ahead": 7}


def _build_rrule(days_of_week: List[str], until_date: Optional[str]) -> str:
    """Build an RFC 5545 RRULE string for a weekly recurring event."""
    days_str = ",".join(days_of_week)
    rrule = f"RRULE:FREQ=WEEKLY;BYDAY={days_str}"
    if until_date:
        until_str = until_date.replace("-", "") + "T235959Z"
        rrule += f";UNTIL={until_str}"
    return rrule


async def handle_schedule(
    sender: str,
    raw_text: str,
    entities: Dict[str, Any],
) -> str:
    """Main entry point for the Schedule Agent. Returns WhatsApp response text."""
    try:
        plan = await plan_action(raw_text, entities)
        action = plan.get("action", "list")

        if action == "create":
            ev_data = plan.get("event", {})
            date_str = ev_data.get("date", datetime.now().strftime("%Y-%m-%d"))
            time_str = ev_data.get("time", "09:00")
            duration = int(ev_data.get("duration_minutes", 60))
            responsible = ev_data.get("responsible") or None

            start_local = AR_TZ.localize(datetime.fromisoformat(f"{date_str}T{time_str}:00"))
            end_local = start_local + timedelta(minutes=duration)

            event = CalendarEvent(
                title=ev_data.get("title", "Evento"),
                start=start_local,
                end=end_local,
                location=ev_data.get("location"),
                responsible_nickname=responsible,
            )
            created = create_event(event)
            date_fmt = start_local.strftime("%-d/%-m a las %H:%M")
            resp_note = f" (responsable: {responsible})" if responsible else ""
            return f"✅ Evento creado: *{created.title}* para el {date_fmt}.{resp_note}"

        elif action == "recurring_create":
            ev_data = plan.get("event", {})
            title = ev_data.get("title", "Evento recurrente")
            start_date = ev_data.get("start_date", datetime.now(AR_TZ).strftime("%Y-%m-%d"))
            until_date = ev_data.get("until_date", f"{datetime.now(AR_TZ).year}-12-31")
            days_of_week: List[str] = ev_data.get("days_of_week", [])
            start_time = ev_data.get("start_time", "09:00")
            end_time = ev_data.get("end_time")
            responsible = ev_data.get("responsible") or None

            if not days_of_week:
                return "No entendí los días de la semana. ¿Me podés decir cuándo se repite?"

            start_local = AR_TZ.localize(
                datetime.fromisoformat(f"{start_date}T{start_time}:00")
            )
            if end_time:
                end_local = AR_TZ.localize(
                    datetime.fromisoformat(f"{start_date}T{end_time}:00")
                )
            else:
                end_local = start_local + timedelta(hours=1)

            rrule = _build_rrule(days_of_week, until_date)

            event = CalendarEvent(
                title=title,
                start=start_local,
                end=end_local,
                location=ev_data.get("location"),
                responsible_nickname=responsible,
            )
            created = create_event(event, recurrence=[rrule])

            day_names = {
                "MO": "lunes", "TU": "martes", "WE": "miércoles",
                "TH": "jueves", "FR": "viernes", "SA": "sábado", "SU": "domingo",
            }
            days_es = ", ".join(day_names.get(d, d) for d in days_of_week)
            time_range = f"{start_time}–{end_time}" if end_time else start_time
            resp_line = f"\n👤 Responsable: {responsible}" if responsible else ""

            return (
                f"✅ Horario recurrente creado: *{created.title}*\n"
                f"📅 {days_es.capitalize()}, {time_range}\n"
                f"🔁 Hasta el {until_date}"
                f"{resp_line}"
            )

        else:
            days = int(plan.get("days_ahead", 7))
            events = list_upcoming_events(days=days)
            return format_events_for_whatsapp(events)

    except Exception:
        logger.exception("schedule_agent_error")
        return "No pude acceder al calendario ahora. Revisá que la cuenta de servicio tenga acceso."
