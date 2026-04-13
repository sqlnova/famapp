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
from core.supabase_client import get_known_places_dict, get_minor_members, resolve_place_address

logger = structlog.get_logger(__name__)

SCHEDULE_SYSTEM_PROMPT = """Sos el agente de calendario de FamApp.
Recibís un mensaje del usuario junto con las entidades ya extraídas por el Intake Agent.

Tu tarea es determinar si el usuario quiere:
- "list"             : consultar próximos eventos
- "create"           : crear uno o varios eventos únicos
- "recurring_create" : crear uno o varios eventos recurrentes

═══════════════════════════════════════════════════
REGLA CRÍTICA — HORARIOS DE CHICOS / ACTIVIDADES
═══════════════════════════════════════════════════
Cuando el usuario describe el horario de un chico (colegio, actividad, etc.)
con un bloque de tiempo (ej. "va de 7:30 a 12"), NO crees un evento que bloquee
ese rango completo en la agenda. Eso es el horario del chico, no una tarea del padre.

En su lugar, creá SIEMPRE DOS eventos cortos (15 min cada uno):
  1. "Llevar [nombre] al [lugar]"  → a la hora de ENTRADA
  2. "Buscar/Retirar [nombre] del [lugar]" → a la hora de SALIDA

Ejemplos:
  "Isabella va al colegio de 8:30 a 11:45, lleva y busca mamá"
  → Evento 1: "Llevar Isabella al colegio"  08:30–08:45  responsible: mama
  → Evento 2: "Retirar Isabella del colegio" 11:45–12:00  responsible: mama

  "Joaquina tiene fútbol los sábados de 10 a 12, la lleva papá y la busco yo"
  → Evento 1: "Llevar Joaquina al fútbol"  10:00–10:15  responsible: papa
  → Evento 2: "Buscar Joaquina del fútbol" 12:00–12:15  responsible: mama

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXCEPCIÓN — VIAJES / PARTIDAS (solo UN evento)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cuando el contexto indica que las personas VAN A VIAJAR y deben estar en un
punto de partida (aeropuerto, terminal de bus, puerto, estación de tren) a cierta
hora, creá SOLO UN evento "Llevar [personas] al [lugar]". NO creés evento de
"Retirar" porque esas personas VIAJAN y no regresan al mismo lugar.

Señales claras de partida (→ un solo evento Llevar):
  - Lugar: aeropuerto, terminal, puerto, estación
  - Frases: "tienen que estar en X", "deben llegar a X", "toman el vuelo/colectivo/tren"
  - La persona que "lleva" ≠ la(s) que viajan (ej: "lleva mamá" significa mamá conduce,
    Giuseppe y papá son los pasajeros que viajan)

Ejemplo correcto:
  "Giuseppe y papá tienen que estar en el aeropuerto a las 20:20, lleva mamá"
  → SOLO Evento 1: "Llevar Giuseppe y papá al aeropuerto"  20:20–20:35  responsible: mama
  (NO crear evento de retirar — Giuseppe y papá viajan en avión)
═══════════════════════════════════════════════════

Campo "responsible":
- Extraé el apodo en minúsculas sin tildes de quien está a cargo.
- "el papá lleva" → "papa" / "yo los busco" / "busca mamá" → "mama"
- Si no se menciona, null.

Para las fechas relativas usá como referencia hoy: {today}
Los horarios son siempre zona horaria Argentina (UTC-3).

Respondé SIEMPRE en JSON sin markdown con arrays "events":
{{
  "action": "list" | "create" | "recurring_create",
  "events": [
    {{
      // Para "create":
      "title": str,
      "date": "YYYY-MM-DD",
      "time": "HH:MM",
      "duration_minutes": int,
      "location": str | null,
      "responsible": str | null,

      // Para "recurring_create" (en lugar de date/time/duration):
      "start_date": "YYYY-MM-DD",
      "until_date": "YYYY-MM-DD",
      "days_of_week": ["MO", "TU", ...],
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "location": str | null,
      "responsible": str | null
    }}
  ],
  "days_ahead": int
}}
"""


def _get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0)


async def plan_action(
    raw_text: str,
    entities: Dict[str, Any],
    places_context: str = "",
    minors_context: str = "",
) -> Dict[str, Any]:
    """Ask LLM to decide list vs create vs recurring_create and fill in event details."""
    llm = _get_llm()
    today = datetime.now(AR_TZ).strftime("%Y-%m-%d (%A)")

    user_content = f"Mensaje: {raw_text}\nEntidades: {json.dumps(entities, ensure_ascii=False)}"
    if places_context or minors_context:
        extra = []
        if minors_context:
            extra.append(minors_context)
        if places_context:
            extra.append(places_context)
        user_content += "\n\n" + "\n".join(extra)

    messages = [
        SystemMessage(content=SCHEDULE_SYSTEM_PROMPT.format(today=today)),
        HumanMessage(content=user_content),
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
        # Load family context from DB
        try:
            known_places = get_known_places_dict()
            minors = get_minor_members()
        except Exception:
            known_places = {}
            minors = []

        places_context = ""
        if known_places:
            lines = [
                f"  • {alias} → {p.address}" + (f" ({p.name})" if p.name.lower() != alias else "")
                for alias, p in known_places.items()
            ]
            places_context = "LUGARES CONOCIDOS (usá la dirección exacta en el campo 'location'):\n" + "\n".join(lines)

        minors_context = ""
        if minors:
            names = ", ".join(m.name for m in minors)
            minors_context = f"MIEMBROS MENORES (aplicar regla llevar+retirar para sus actividades): {names}"

        plan = await plan_action(raw_text, entities, places_context, minors_context)
        action = plan.get("action", "list")

        if action == "create":
            # Support both `events: [...]` (new) and `event: {...}` (legacy)
            ev_list = plan.get("events") or ([plan["event"]] if plan.get("event") else [])
            if not ev_list:
                return "No pude entender qué evento crear. ¿Podés darme más detalles?"

            created_msgs = []
            for ev_data in ev_list:
                date_str = ev_data.get("date", datetime.now().strftime("%Y-%m-%d"))
                time_str = ev_data.get("time", "09:00")
                duration = int(ev_data.get("duration_minutes", 60))
                responsible = ev_data.get("responsible") or None
                # Resolve location alias → full address (fallback if LLM didn't resolve it)
                location = resolve_place_address(ev_data.get("location") or "", known_places) or None

                start_local = AR_TZ.localize(datetime.fromisoformat(f"{date_str}T{time_str}:00"))
                end_local = start_local + timedelta(minutes=duration)

                event = CalendarEvent(
                    title=ev_data.get("title", "Evento"),
                    start=start_local,
                    end=end_local,
                    location=location,
                    responsible_nickname=responsible,
                )
                created = create_event(event)
                date_fmt = start_local.strftime("%-d/%-m a las %H:%M")
                resp_note = f" ({responsible})" if responsible else ""
                created_msgs.append(f"• *{created.title}* — {date_fmt}{resp_note}")

            header = "✅ Evento creado:" if len(created_msgs) == 1 else f"✅ {len(created_msgs)} eventos creados:"
            return header + "\n" + "\n".join(created_msgs)

        elif action == "recurring_create":
            # Support both `events: [...]` (new) and `event: {...}` (legacy)
            ev_list = plan.get("events") or ([plan["event"]] if plan.get("event") else [])
            if not ev_list:
                return "No pude entender qué horario cargar. ¿Podés darme más detalles?"

            DAY_NAMES = {
                "MO": "lunes", "TU": "martes", "WE": "miércoles",
                "TH": "jueves", "FR": "viernes", "SA": "sábado", "SU": "domingo",
            }
            created_msgs = []

            for ev_data in ev_list:
                title = ev_data.get("title", "Evento recurrente")
                start_date = ev_data.get("start_date", datetime.now(AR_TZ).strftime("%Y-%m-%d"))
                until_date = ev_data.get("until_date", f"{datetime.now(AR_TZ).year}-12-31")
                days_of_week: List[str] = ev_data.get("days_of_week", [])
                start_time = ev_data.get("start_time", "09:00")
                end_time = ev_data.get("end_time")
                responsible = ev_data.get("responsible") or None

                if not days_of_week:
                    continue

                start_local = AR_TZ.localize(
                    datetime.fromisoformat(f"{start_date}T{start_time}:00")
                )
                if end_time:
                    end_local = AR_TZ.localize(
                        datetime.fromisoformat(f"{start_date}T{end_time}:00")
                    )
                else:
                    end_local = start_local + timedelta(minutes=15)

                rrule = _build_rrule(days_of_week, until_date)
                rec_location = resolve_place_address(ev_data.get("location") or "", known_places) or None
                event = CalendarEvent(
                    title=title,
                    start=start_local,
                    end=end_local,
                    location=rec_location,
                    responsible_nickname=responsible,
                )
                create_event(event, recurrence=[rrule])

                days_es = ", ".join(DAY_NAMES.get(d, d) for d in days_of_week)
                time_range = f"{start_time}–{end_time}" if end_time else start_time
                resp_note = f" ({responsible})" if responsible else ""
                created_msgs.append(f"• *{title}* — {days_es}, {time_range}{resp_note}")

            if not created_msgs:
                return "No pude entender los días. ¿Me podés decir cuándo se repite?"

            header = "✅ Horario recurrente creado:" if len(created_msgs) == 1 else f"✅ {len(created_msgs)} eventos recurrentes creados:"
            # Show until date from the last event processed
            until_note = f"\n🔁 Hasta el {until_date}" if until_date else ""
            return header + "\n" + "\n".join(created_msgs) + until_note

        else:
            days = int(plan.get("days_ahead", 7))
            events = list_upcoming_events(days=days)
            return format_events_for_whatsapp(events)

    except Exception:
        logger.exception("schedule_agent_error")
        return "No pude acceder al calendario ahora. Revisá que la cuenta de servicio tenga acceso."
