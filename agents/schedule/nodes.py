"""Schedule Agent – LangGraph nodes."""
from __future__ import annotations

import json
import re
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytz
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.schedule.calendar_client import (
    AR_TZ,
    create_event,
    delete_event,
    format_events_for_whatsapp,
    list_upcoming_events,
    list_recurring_series,
    update_event,
)
from core.config import get_settings
from core.models import CalendarEvent
from core.supabase_client import (
    get_family_members,
    get_known_places_dict,
    get_minor_members,
    resolve_place_address,
)

logger = structlog.get_logger(__name__)

SCHEDULE_SYSTEM_PROMPT = """Sos el agente de calendario de FamApp.
Recibís un mensaje del usuario junto con las entidades ya extraídas por el Intake Agent.

Tu tarea es determinar si el usuario quiere:
- "list"             : consultar próximos eventos
- "create"           : crear uno o varios eventos únicos
- "recurring_create" : crear uno o varios eventos recurrentes
- "update"           : modificar un evento existente
- "delete"           : eliminar un evento existente

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
  "action": "list" | "create" | "recurring_create" | "update" | "delete",
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
    }},
    {{
      // Para "update" o "delete":
      "target": str,               // texto para identificar evento (título/lugar)
      "date": "YYYY-MM-DD" | null, // opcional para desambiguar

      // Solo para "update" (campos a cambiar):
      "new_title": str | null,
      "new_date": "YYYY-MM-DD" | null,
      "new_time": "HH:MM" | null,
      "new_duration_minutes": int | null,
      "new_location": str | null,
      "new_responsible": str | null
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


def _normalize_time_str(raw: Any, default: str = "09:00") -> str:
    """Normalize flexible time strings into HH:MM 24-hour format.

    Accepts variants commonly used in WhatsApp messages:
    - "7.30", "7:30", "07:30"
    - "7:30 am", "12pm"
    - "14hs", "17 hs", "14 h"
    - "7" (treated as 07:00)
    """
    if raw is None:
        return default

    text = str(raw).strip().lower()
    if not text:
        return default

    # Normalize separators and remove common Spanish suffixes.
    text = text.replace(".", ":")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*h(?:s)?\b", "", text).strip()

    # HH(:MM)? with optional am/pm
    m = re.match(r"^(\d{1,2})(?::(\d{1,2}))?\s*(am|pm)?$", text)
    if not m:
        return default

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridian = m.group(3)

    if minute < 0 or minute > 59:
        return default

    if meridian:
        if hour < 1 or hour > 12:
            return default
        if meridian == "am":
            hour = 0 if hour == 12 else hour
        else:  # pm
            hour = 12 if hour == 12 else hour + 12
    else:
        if hour < 0 or hour > 23:
            return default

    return f"{hour:02d}:{minute:02d}"


def _has_explicit_start_date(raw_text: str) -> bool:
    """Heuristic: user explicitly mentioned a concrete start date."""
    txt = raw_text or ""
    return bool(
        re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", txt)
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", txt)
    )


def _canonicalize_responsible(raw: Any, alias_map: Dict[str, str]) -> Optional[str]:
    if raw is None:
        return None
    key = _normalize_text(str(raw))
    return alias_map.get(key, key or None)


def _build_responsible_alias_map() -> Dict[str, str]:
    """Build alias -> canonical nickname map from family members plus common parent aliases."""
    alias_map: Dict[str, str] = {}
    try:
        members = get_family_members()
    except Exception:
        members = []

    for m in members:
        canonical = _normalize_text(m.nickname)
        if canonical:
            alias_map[canonical] = canonical
        name_key = _normalize_text(m.name)
        if name_key:
            alias_map[name_key] = canonical

    # Parent-role aliases. Prefer configured parent nicknames when present.
    mother = alias_map.get("mama") or alias_map.get("mamá") or alias_map.get("julieta") or "mama"
    father = alias_map.get("papa") or alias_map.get("papá") or alias_map.get("mauro") or "papa"
    for k in ["mama", "mamá", "madre", "mother"]:
        alias_map[_normalize_text(k)] = mother
    for k in ["papa", "papá", "padre", "father"]:
        alias_map[_normalize_text(k)] = father

    return alias_map


def _infer_action_for_time(raw_text: str, hhmm: str) -> Optional[str]:
    """Infer whether an event at hhmm is a dropoff (llevar) or pickup (buscar/retirar)."""
    chunks = [c for c in (raw_text or "").splitlines() if c.strip()]
    for raw_chunk in chunks:
        chunk = _normalize_text(raw_chunk)
        matches = re.findall(r"\b\d{1,2}(?::\d{1,2}|\.\d{1,2})?\s*(?:am|pm|hs?)?\b", chunk)
        if hhmm not in {_normalize_time_str(m, default="") for m in matches}:
            continue
        if any(k in chunk for k in ["retira", "retirar", "busca", "buscar", "sale", "salen"]):
            return "buscar"
        if any(k in chunk for k in ["lleva", "llevar", "ingresa", "ingresan", "entra", "entran", " va ", " van "]):
            return "llevar"
    return None


def _infer_people_for_time(raw_text: str, hhmm: str, minor_names: List[str]) -> str:
    chunks = [c for c in (raw_text or "").splitlines() if c.strip()]
    names_n = [(_normalize_text(n), n) for n in minor_names if n]
    for raw_chunk in chunks:
        chunk = _normalize_text(raw_chunk)
        matches = re.findall(r"\b\d{1,2}(?::\d{1,2}|\.\d{1,2})?\s*(?:am|pm|hs?)?\b", chunk)
        if hhmm not in {_normalize_time_str(m, default="") for m in matches}:
            continue
        found = [display for nrm, display in names_n if nrm and nrm in chunk]
        if found:
            if len(found) == 1:
                return found[0]
            if len(found) == 2:
                return f"{found[0]} y {found[1]}"
            return ", ".join(found[:-1]) + f" y {found[-1]}"
    return ""


def _build_fallback_title(raw_text: str, start_time: str, location: Optional[str], minor_names: List[str]) -> str:
    action = _infer_action_for_time(raw_text, start_time) or "llevar"
    people = _infer_people_for_time(raw_text, start_time, minor_names)
    loc_n = _normalize_text(location or "")
    if "colegio" in loc_n:
        place_phrase = "al colegio" if action == "llevar" else "del colegio"
    elif location:
        place_phrase = f"a {location}" if action == "llevar" else f"de {location}"
    else:
        place_phrase = ""

    verb = "Llevar" if action == "llevar" else "Buscar"
    if people:
        return f"{verb} {people} {place_phrase}".strip()
    return f"{verb} {place_phrase}".strip()


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
            responsible_aliases = _build_responsible_alias_map()
        except Exception:
            known_places = {}
            minors = []
            responsible_aliases = _build_responsible_alias_map()

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
        raw_norm = _normalize_text(raw_text)
        minor_names = [m.name for m in minors]

        # Fallback: if LLM missed update/delete intent from natural language, force it.
        if plan.get("action") not in {"update", "delete"}:
            if any(v in raw_norm for v in ["elimina", "eliminar", "borrar", "borra", "cancela", "cancelar"]):
                plan = {"action": "delete", "events": []}
            elif any(v in raw_norm for v in ["modifica", "modificar", "cambia", "cambiar", "renombra", "renombrar"]):
                plan = {"action": "update", "events": []}

        if plan.get("action") == "delete" and not plan.get("events"):
            # "eliminar todos los eventos recurrentes"
            if "recurrent" in raw_norm and any(x in raw_norm for x in ["todo", "todos", "todas"]):
                plan["events"] = [{"target": "__all_recurring__"}]

        if plan.get("action") == "update" and not plan.get("events"):
            # "cambia nombre del evento recurrente de las 11.30 por Retirar..."
            inferred = _infer_update_from_text(raw_text)
            if inferred:
                plan["events"] = [inferred]

        action = plan.get("action", "list")

        if action == "create":
            # Support both `events: [...]` (new) and `event: {...}` (legacy)
            ev_list = plan.get("events") or ([plan["event"]] if plan.get("event") else [])
            if not ev_list:
                return "No pude entender qué evento crear. ¿Podés darme más detalles?"

            created_msgs = []
            for ev_data in ev_list:
                date_str = ev_data.get("date", datetime.now().strftime("%Y-%m-%d"))
                time_str = _normalize_time_str(ev_data.get("time"), default="09:00")
                duration = int(ev_data.get("duration_minutes", 60))
                responsible = _canonicalize_responsible(ev_data.get("responsible"), responsible_aliases)
                # Resolve location alias → full address (fallback if LLM didn't resolve it)
                location = resolve_place_address(ev_data.get("location") or "", known_places) or None
                title = (ev_data.get("title") or "").strip()
                if not title or _normalize_text(title) in {"evento", "evento recurrente"}:
                    title = _build_fallback_title(raw_text, time_str, location, minor_names)

                start_local = AR_TZ.localize(datetime.fromisoformat(f"{date_str}T{time_str}:00"))
                end_local = start_local + timedelta(minutes=duration)

                event = CalendarEvent(
                    title=title,
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
                title = (ev_data.get("title") or "").strip()
                start_date = ev_data.get("start_date", datetime.now(AR_TZ).strftime("%Y-%m-%d"))
                if not _has_explicit_start_date(raw_text):
                    # If user did not explicitly provide a start date, begin today.
                    start_date = datetime.now(AR_TZ).strftime("%Y-%m-%d")
                until_date = ev_data.get("until_date", f"{datetime.now(AR_TZ).year}-12-31")
                days_of_week: List[str] = ev_data.get("days_of_week", [])
                start_time = _normalize_time_str(ev_data.get("start_time"), default="09:00")
                end_time = _normalize_time_str(ev_data.get("end_time"), default="09:15") if ev_data.get("end_time") else None
                responsible = _canonicalize_responsible(ev_data.get("responsible"), responsible_aliases)
                rec_location = resolve_place_address(ev_data.get("location") or "", known_places) or None

                if not title or _normalize_text(title) in {"evento", "evento recurrente"}:
                    title = _build_fallback_title(raw_text, start_time, rec_location, minor_names)

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

        elif action in {"update", "delete"}:
            ev_list = plan.get("events") or ([plan["event"]] if plan.get("event") else [])
            if not ev_list:
                return "No pude identificar qué evento querés modificar/eliminar."

            upcoming = list_upcoming_events(days=120, max_results=300)
            results: List[str] = []
            for ev_data in ev_list:
                target = (ev_data.get("target") or "").strip().lower()
                target_date = ev_data.get("date")
                is_recurring_request = "recurrent" in raw_norm or "recurrente" in target

                if action == "delete" and target == "__all_recurring__":
                    recurring_series = list_recurring_series(days=365, max_results=250)
                    if not recurring_series:
                        results.append("No encontré eventos recurrentes para eliminar.")
                        continue
                    for rec_event in recurring_series:
                        if rec_event.id:
                            delete_event(rec_event.id)
                    results.append(f"🗑️ Eliminé {len(recurring_series)} series de eventos recurrentes.")
                    continue

                candidates = [
                    e for e in upcoming
                    if _event_matches_target(e, target, raw_text)
                ]
                if is_recurring_request:
                    candidates = [e for e in candidates if not e.alerts_enabled]
                if target_date:
                    candidates = [
                        e for e in candidates
                        if e.start.astimezone(AR_TZ).strftime("%Y-%m-%d") == target_date
                    ]

                if not candidates:
                    date_note = f" del {target_date}" if target_date else ""
                    results.append(f"⚠️ No encontré eventos para '{target or 'ese criterio'}'{date_note}.")
                    continue
                if len(candidates) > 1:
                    preview = "\n".join(
                        f"• {e.title} ({e.start.astimezone(AR_TZ).strftime('%-d/%-m %H:%M')})"
                        for e in candidates[:3]
                    )
                    results.append(
                        "⚠️ Encontré varios eventos posibles. Decime uno más específico:\n" + preview
                    )
                    continue

                event = candidates[0]
                if not event.id:
                    results.append(f"⚠️ No pude identificar el ID de *{event.title}* para operar.")
                    continue
                if action == "delete":
                    delete_event(event.id)
                    results.append(f"🗑️ Eliminé *{event.title}*.")
                    continue

                current_local_start = event.start.astimezone(AR_TZ)
                new_date = ev_data.get("new_date")
                new_time = ev_data.get("new_time")
                new_duration = ev_data.get("new_duration_minutes")
                if new_duration is None:
                    current_duration = int((event.end - event.start).total_seconds() // 60)
                    duration_minutes = current_duration if current_duration > 0 else 60
                else:
                    duration_minutes = int(new_duration)

                updated_start = event.start
                updated_end = event.end
                if new_date or new_time:
                    use_date = new_date or current_local_start.strftime("%Y-%m-%d")
                    use_time = new_time or current_local_start.strftime("%H:%M")
                    updated_start = AR_TZ.localize(datetime.fromisoformat(f"{use_date}T{use_time}:00"))
                    updated_end = updated_start + timedelta(minutes=duration_minutes)

                updates: Dict[str, Any] = {"start": updated_start, "end": updated_end}
                if "new_title" in ev_data:
                    updates["title"] = ev_data.get("new_title")
                if "new_location" in ev_data:
                    updates["location"] = resolve_place_address(ev_data.get("new_location") or "", known_places)
                if "new_responsible" in ev_data:
                    updates["responsible_nickname"] = _canonicalize_responsible(
                        ev_data.get("new_responsible"), responsible_aliases
                    )

                updated = update_event(event.id, updates)
                results.append(
                    f"✏️ Actualicé *{updated.title}* para {updated.start.astimezone(AR_TZ).strftime('%-d/%-m %H:%M')}."
                )

            return "\n".join(results)

        else:
            days = int(plan.get("days_ahead", 7))
            events = list_upcoming_events(days=days)
            return format_events_for_whatsapp(events)

    except Exception:
        logger.exception("schedule_agent_error")
        return "No pude acceder al calendario ahora. Revisá que la cuenta de servicio tenga acceso."


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s:.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_time_tokens(text: str) -> List[str]:
    text_n = _normalize_text(text)
    found = re.findall(r"\b(\d{1,2})[:.](\d{2})\b", text_n)
    tokens = []
    for hh, mm in found:
        tokens.append(f"{int(hh):02d}:{mm}")
    return tokens


def _event_matches_target(event: CalendarEvent, target: str, full_text: str) -> bool:
    if not target:
        return True
    title = _normalize_text(event.title)
    location = _normalize_text(event.location or "")
    target_n = _normalize_text(target)

    if target_n in title or target_n in location:
        return True

    # Token overlap fallback (for natural language fragments).
    ignore = {"evento", "recurrente", "recurrentes", "de", "del", "las", "los", "la", "el"}
    target_tokens = [t for t in target_n.split() if len(t) > 2 and t not in ignore]
    if target_tokens and sum(1 for t in target_tokens if t in title or t in location) >= max(1, len(target_tokens) // 2):
        return True

    # Time-based fallback: "de las 11.30".
    requested_times = _extract_time_tokens(f"{target} {full_text}")
    if requested_times:
        ev_time = event.start.astimezone(AR_TZ).strftime("%H:%M")
        if ev_time in requested_times:
            return True

    return False


def _infer_update_from_text(raw_text: str) -> Optional[Dict[str, Any]]:
    raw_n = _normalize_text(raw_text)
    if not any(v in raw_n for v in ["modifica", "modificar", "cambia", "cambiar", "renombra", "renombrar"]):
        return None

    time_match = re.search(r"de las?\s+(\d{1,2}[:.]\d{2})", raw_n)
    new_title = None
    if " por " in raw_n:
        new_title = raw_text.split(" por ", 1)[1].strip()

    inferred: Dict[str, Any] = {"target": "recurrente" if "recurrent" in raw_n else ""}
    if time_match:
        hhmm = time_match.group(1).replace(".", ":")
        h, m = hhmm.split(":")
        inferred["target"] = f"{inferred['target']} {int(h):02d}:{m}".strip()
    if new_title:
        inferred["new_title"] = new_title
    return inferred
