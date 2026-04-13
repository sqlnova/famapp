"""Schedule Agent – LangGraph nodes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

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
- "list"   : consultar próximos eventos (ej. "¿qué tengo mañana?")
- "create" : crear un nuevo evento

Para "create", debés completar el evento con los datos disponibles:
- Si falta la hora, usá 09:00 como default.
- Si falta la duración, usá 1 hora.
- Las fechas relativas (mañana, próximo lunes, etc.) calcularlas desde hoy: {today}
- Los horarios son siempre en zona horaria Argentina (UTC-3)

Respondé SIEMPRE en JSON sin markdown:
{{
  "action": "list" | "create",
  "event": {{             // solo para create
    "title": str,
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "duration_minutes": int,
    "location": str | null
  }},
  "days_ahead": int       // solo para list: cuántos días mostrar (default 7)
}}
"""


def _get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0)


async def plan_action(raw_text: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Ask LLM to decide list vs create and fill in event details."""
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

            start_local = AR_TZ.localize(datetime.fromisoformat(f"{date_str}T{time_str}:00"))
            end_local = start_local + timedelta(minutes=duration)

            event = CalendarEvent(
                title=ev_data.get("title", "Evento"),
                start=start_local,
                end=end_local,
                location=ev_data.get("location"),
            )
            created = create_event(event)
            date_fmt = start_local.strftime("%-d/%-m a las %H:%M")
            return f"✅ Evento creado: *{created.title}* para el {date_fmt}."

        else:
            days = int(plan.get("days_ahead", 7))
            events = list_upcoming_events(days=days)
            return format_events_for_whatsapp(events)

    except Exception:
        logger.exception("schedule_agent_error")
        return "No pude acceder al calendario ahora. Revisá que la cuenta de servicio tenga acceso."
