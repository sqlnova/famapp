"""Intake Agent – LangGraph node implementations."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.intake_fallbacks import detect_fallback_route
from core.config import get_settings
from core.models import IntentType
from agents.intake.state import IntakeState
from famapp.monitoring import send_event

logger = structlog.get_logger(__name__)


def _get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.openai_model,
        api_key=s.openai_api_key,
        temperature=0,
    )


SYSTEM_PROMPT = """Sos el agente de recepción (Intake) de FamApp, un sistema familiar de logística.
Tu tarea es analizar mensajes de WhatsApp de miembros de la familia y:

1. Clasificar la INTENCIÓN principal en:
   - "schedule"  : TODO lo relacionado con el calendario — agendar, modificar, cancelar o CONSULTAR eventos.
                   Usá "schedule" cuando pregunten qué tienen pendiente, qué hay esta semana, cuándo es algo, etc.
                   Usá "schedule" también cuando alguien ENUNCIA un plan futuro: una persona va a algún lugar
                   a una hora determinada, aunque no digan explícitamente "agenda" o "anotá".
                   Ejemplos: "¿qué tengo mañana?", "agendame el dentista", "mañana papá lleva a los chicos al club a las 16",
                             "Giuseppe y papá tienen que estar en el aeropuerto a las 20:20, lleva mamá",
                             "hoy papá lleva a Gaetano al colegio a las 8:30"
   - "logistics" : preguntas sobre tiempo de viaje/tráfico, O cuando el usuario pide que se le avise
                   antes de un evento específico (incluso recurrente).
                   Ejemplos travel_time: "¿cuánto tardo en llegar a Palermo?", "¿a qué hora salgo?"
                   Ejemplos request_alert: "avisame antes del colegio de mañana",
                             "quiero notificación para el club del jueves",
                             "recordame salir para el dentista del viernes",
                             "avisame para llevar a Gaetano al colegio el lunes"
                   NO uses "logistics" cuando el usuario simplemente enuncia un plan o evento futuro.
   - "shopping"  : lista de compras — agregar, consultar o tachar items.
                   Ejemplos: "agregá leche", "¿qué falta comprar?", "comprar pan y huevos",
                             "tachá la leche", "ya compré el pan", "marca el aceite como comprado"
   - "places"   : guardar o consultar los lugares frecuentes de la familia.
                   Guardá cuando el usuario registre una dirección con un nombre corto, o cuando
                   aclare "cada vez que diga X me refiero a Y".
                   Ejemplos: "el colegio es en Av. San Martín 123, Resistencia",
                             "guarda que el club es en Av Ávalos 1085",
                             "cada vez que diga supermercado es el Jumbo de Av. Alberdi 200",
                             "¿qué lugares tenemos guardados?"
   - "expense"  : registrar o consultar un gasto del hogar.
                   Ejemplos: "gasté $8500 en el súper", "anoté $1200 en farmacia",
                             "papá pagó $3000 de nafta", "¿cuánto gastamos este mes?",
                             "¿qué gastos tenemos esta semana?"
   - "homework"  : tareas o deberes de los chicos.
                   Ejemplos: "Giuseppe tiene que entregar la maqueta el viernes",
                             "Gaetano tiene que estudiar matemáticas para el lunes",
                             "¿qué tareas tienen pendientes?", "ya entregó el trabajo de lengua"
   - "memory"   : recordar o consultar datos importantes de la familia (preferencias, médicos, etc.).
                   Ejemplos: "guardá que Gaetano no come mariscos",
                             "el pediatra de los chicos es el Dr. Ruiz, tel 362-123456",
                             "¿qué recordás de Giuseppe?", "¿tenemos info sobre la dieta de alguien?"
   - "unknown"   : no podés determinar la intención con certeza

   REGLA CLAVE: Si el mensaje menciona a una persona que va a algún lugar a una hora específica
   (ej: "papá lleva a X al club a las 16", "tienen que estar en Y a las 20"), clasificalo como
   "schedule" — el agente de calendario se encargará de crearlo aunque no digan "agenda".

   IMPORTANTE: Nunca uses "unknown" si el mensaje claramente habla de calendario, viajes, compras,
   gastos, tareas escolares o información familiar. La categoría "query" NO EXISTE.

2. Extraer ENTIDADES según la intención:
   - schedule  → { "title": str, "date": str, "time": str, "location": str, "people": [str] }
   - logistics → {
       "action": "travel_time" | "request_alert",
       "destination": str, "event_time": str, "origin": str,
       "event_name": str, "date": "YYYY-MM-DD"
     }
   - shopping  → {
       "action": "add" | "list" | "mark_done",
       "items": [{"name": str, "quantity": str, "unit": str}]
     }
     Para "mark_done" los items contienen solo el nombre de lo que ya se compró.
   - places    → {
       "action": "save" | "list",
       "alias": str, "name": str, "address": str
     }
   - expense   → {
       "action": "add" | "list",
       "description": str,        // qué se compró/pagó
       "amount": float,           // monto sin símbolo de moneda
       "category": str,           // Supermercado | Farmacia | Combustible | Servicios | Salud | Educación | Ocio | General
       "paid_by": str | null,     // nickname de quien pagó (null = no especificado)
       "date": "YYYY-MM-DD" | null  // null = hoy
     }
   - homework  → {
       "action": "add" | "list" | "mark_done",
       "child_name": str,         // nombre del chico
       "subject": str,            // materia (ej: "Matemáticas", "Lengua")
       "description": str,        // detalle de la tarea
       "due_date": "YYYY-MM-DD"   // fecha de entrega
     }
   - memory    → {
       "action": "save" | "query",
       "subject": str,    // nickname o tema ("gaetano", "salud", "general")
       "note": str        // contenido a recordar (para "save"), o null para "query"
     }

3. Responder en español rioplatense informal y breve.

Devolvé SIEMPRE JSON sin markdown:
{
  "intent": "<intención>",
  "confidence": <0.0-1.0>,
  "entities": { ... },
  "summary": "<resumen breve>",
  "response": "<respuesta directa solo si podés resolver sin sub-agentes, o null>"
}
"""


def _build_history_context(sender: str) -> str:
    """Return the last 3 messages from this sender as context string."""
    try:
        from core.supabase_client import get_recent_messages_from_sender
        history = get_recent_messages_from_sender(sender, limit=3)
        if not history:
            return ""
        lines = ["HISTORIAL RECIENTE (últimos mensajes del mismo remitente):"]
        for msg in history:
            body = msg.get("body", "")
            response = msg.get("response", "")
            if body:
                lines.append(f"  Usuario: {body}")
            if response:
                lines.append(f"  FamApp:  {response}")
        return "\n".join(lines)
    except Exception:
        return ""


def _resolve_sender_nickname(sender: str) -> Optional[str]:
    """Attempt to resolve the sender's WhatsApp number to their family nickname."""
    try:
        from core.supabase_client import get_family_member_by_phone
        member = get_family_member_by_phone(sender)
        return member.nickname if member else None
    except Exception:
        return None


async def parse_and_classify(state: IntakeState) -> Dict[str, Any]:
    """LLM call to parse intent and extract entities.
    Includes message history and sender identity for context.
    """
    await send_event("intake", "active", "Classifying incoming message")
    llm = _get_llm()

    # Resolve sender identity once per message
    sender_nickname = state.get("sender_nickname") or _resolve_sender_nickname(state["sender"])

    # Build user content with context
    user_parts = []
    if sender_nickname:
        user_parts.append(f"[Remitente: {sender_nickname}]")
    history = _build_history_context(state["sender"])
    if history:
        user_parts.append(history)
    user_parts.append(f"Mensaje actual: {state['raw_text']}")
    user_content = "\n\n".join(user_parts)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    logger.info("intake_parsing", sender=state["sender"], raw_text=state["raw_text"])
    response = await llm.ainvoke(messages)
    content = response.content

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}

    intent_str = parsed.get("intent", "unknown")
    try:
        intent = IntentType(intent_str)
    except ValueError:
        intent = IntentType.UNKNOWN

    logger.info(
        "intake_classified",
        raw_text=state["raw_text"],
        intent=intent.value,
        confidence=parsed.get("confidence", 0.0),
        entities=parsed.get("entities", {}),
    )

    await send_event("intake", "idle", f"Intent={intent.value}")

    return {
        "messages": state["messages"] + [HumanMessage(content=state["raw_text"]), response],
        "intent": intent,
        "confidence": float(parsed.get("confidence", 0.0)),
        "entities": parsed.get("entities", {}),
        "summary": parsed.get("summary", ""),
        "response_text": parsed.get("response"),
        "sender_nickname": sender_nickname,
    }


def _clean_shopping_item_name(name: str) -> str:
    cleaned = (name or "").strip().lower()
    cleaned = re.sub(r"^(comprar|compra|agregar|agrega|agregá|agregue|anota|anotá)\s+", "", cleaned)
    cleaned = re.sub(r"^(la|el|los|las|un|una)\s+", "", cleaned)
    return cleaned.strip(" .,!?:;")


def _infer_shopping_action(entities: Dict[str, Any], raw_text: str) -> str:
    action = (entities.get("action", "") if isinstance(entities, dict) else "").strip().lower()
    if action in {"add", "list", "mark_done"}:
        return action

    normalized = (raw_text or "").strip().lower()
    if not normalized:
        return "list"

    is_question = "?" in normalized or normalized.startswith(("que ", "qué ", "cual ", "cuál "))
    list_patterns = (
        "lista de compras",
        "que hay",
        "qué hay",
        "que tengo que comprar",
        "qué tengo que comprar",
        "que falta comprar",
        "qué falta comprar",
    )
    if is_question and any(p in normalized for p in list_patterns):
        return "list"

    if any(
        k in normalized
        for k in (
            "tacha",
            "tachá",
            "ya compre",
            "ya compré",
            "comprado",
            "marca ",
            "eliminar ",
            "elimina ",
            "tachar todo",
            "elimina todo",
            "todo",
            "todos",
            "compra realizada",
            "compras realizadas",
        )
    ):
        return "mark_done"

    return "add"


def _extract_shopping_items(entities: Dict[str, Any], raw_text: str, action: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    raw_items = entities.get("items", []) if isinstance(entities, dict) else []
    for item in raw_items:
        if isinstance(item, dict):
            name = _clean_shopping_item_name(str(item.get("name", "")))
            if not name:
                continue
            items.append(
                {
                    "name": name,
                    "quantity": str(item.get("quantity", "") or ""),
                    "unit": str(item.get("unit", "") or ""),
                }
            )
        elif isinstance(item, str):
            name = _clean_shopping_item_name(item)
            if name:
                items.append({"name": name, "quantity": "", "unit": ""})

    if items:
        return items

    text = (raw_text or "").strip()
    if not text:
        return []
    if action != "add":
        return []
    normalized = text.lower()
    normalized = re.sub(r"^(comprar|compra|agregar|agrega|agregá|anota|anotá)\s+", "", normalized)
    parts = re.split(r",| y | e |;", normalized)
    deduped: List[Dict[str, str]] = []
    seen = set()
    for part in parts:
        name = _clean_shopping_item_name(part)
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append({"name": name, "quantity": "", "unit": ""})
    return deduped


def _is_bulk_mark_done_request(raw_text: str) -> bool:
    normalized = (raw_text or "").strip().lower()
    bulk_patterns = (
        "tachar todo",
        "tacha todo",
        "tachá todo",
        "elimina todo",
        "eliminar todo",
        "borrar todo",
        "marcar todo",
        "todo comprado",
        "compra realizada",
        "compras realizadas",
        "todos",
        "todo",
    )
    return any(p in normalized for p in bulk_patterns)


async def handle_shopping(state: IntakeState) -> Dict[str, Any]:
    """Process shopping requests within Intake."""
    from agents.intake.tools import add_item_to_shopping_list, list_shopping_items, mark_all_items_done, mark_items_done

    await send_event("shopping", "active", "Handling shopping request")
    entities = state.get("entities", {})
    action = _infer_shopping_action(entities, state.get("raw_text", ""))
    items = _extract_shopping_items(entities, state.get("raw_text", ""), action)
    logger.info(
        "intake_shopping_handler_input",
        raw_text=state.get("raw_text", ""),
        intent=(state.get("intent") or IntentType.UNKNOWN).value,
        entities=entities,
        action=action,
        items=items,
    )

    try:
        if action == "mark_done":
            if _is_bulk_mark_done_request(state.get("raw_text", "")):
                response_text = await mark_all_items_done.ainvoke({})
            else:
                names = [item.get("name", "") for item in items if item.get("name")]
                if names:
                    response_text = await mark_items_done.ainvoke({"names": names})
                else:
                    response_text = "¿Qué ítem querés tachar de la lista?"

        elif items:
            responses = []
            for item in items:
                result = await add_item_to_shopping_list.ainvoke({
                    "name": item.get("name", ""),
                    "quantity": item.get("quantity", ""),
                    "unit": item.get("unit", ""),
                    "added_by": state["sender"],
                })
                responses.append(result)
            response_text = " ".join(responses)

        else:
            response_text = await list_shopping_items.ainvoke({})
    except Exception as exc:
        logger.exception(
            "shopping_handler_error",
            raw_text=state.get("raw_text", ""),
            intent=(state.get("intent") or IntentType.UNKNOWN).value,
            entities=entities,
        )
        await send_event("shopping", "error", f"Shopping failed: {exc}")
        raise

    await send_event("shopping", "idle", f"action={action} items={len(items)}")
    return {"response_text": response_text, "route_to": "direct"}


async def handle_schedule(state: IntakeState) -> Dict[str, Any]:
    """Delegate to the Schedule Agent (Google Calendar)."""
    from agents.schedule.nodes import handle_schedule as schedule_handler
    await send_event("schedule", "active", "Handling schedule request")
    try:
        response_text = await schedule_handler(
            sender=state["sender"],
            raw_text=state["raw_text"],
            entities=state.get("entities", {}),
        )
    except Exception as exc:
        await send_event("schedule", "error", f"Schedule failed: {exc}")
        raise
    await send_event("schedule", "idle", "Schedule request completed")
    return {"response_text": response_text, "route_to": "schedule"}


async def handle_places(state: IntakeState) -> Dict[str, Any]:
    """Save or list known family places."""
    from core.supabase_client import get_all_known_places, upsert_known_place

    entities = state.get("entities", {})
    action = entities.get("action", "list")
    alias = (entities.get("alias") or "").strip().lower()
    name = (entities.get("name") or alias).strip()
    address = (entities.get("address") or "").strip()

    if action == "save":
        if not alias or not address:
            return {"response_text": "Necesito el nombre corto y la dirección. Ej: 'el colegio es en Av. X 123, Resistencia'"}
        upsert_known_place(alias, name or alias, address)
        return {"response_text": f"✅ Guardé *{alias}* → {address}"}

    # list
    places = get_all_known_places()
    if not places:
        return {"response_text": "No tenés lugares guardados todavía.\nEjemplo: 'el colegio es en Av. X 123, Resistencia'"}
    lines = [f"• *{p.alias}*: {p.name}\n  📍 {p.address}" for p in places]
    return {"response_text": "📍 *Lugares guardados:*\n" + "\n".join(lines)}


async def handle_logistics(state: IntakeState) -> Dict[str, Any]:
    """Delegate to the Logistics Agent (Google Maps)."""
    from agents.logistics import handle_logistics_query
    await send_event("logistics", "active", "Handling logistics request")
    try:
        response_text = await handle_logistics_query(
            sender=state["sender"],
            entities=state.get("entities", {}),
            message_sid=state["message_sid"],
        )
    except Exception as exc:
        await send_event("logistics", "error", f"Logistics failed: {exc}")
        raise
    await send_event("logistics", "idle", "Logistics request completed")
    return {"response_text": response_text, "route_to": "logistics"}


async def handle_expense(state: IntakeState) -> Dict[str, Any]:
    """Record or query family expenses."""
    from agents.expenses import handle_expense_request
    response_text = await handle_expense_request(
        sender=state["sender"],
        sender_nickname=state.get("sender_nickname"),
        entities=state.get("entities", {}),
    )
    return {"response_text": response_text, "route_to": "direct"}


async def handle_homework(state: IntakeState) -> Dict[str, Any]:
    """Record or query children's homework tasks."""
    from agents.homework import handle_homework_request
    response_text = await handle_homework_request(
        sender=state["sender"],
        entities=state.get("entities", {}),
    )
    return {"response_text": response_text, "route_to": "direct"}


async def handle_memory(state: IntakeState) -> Dict[str, Any]:
    """Save or query family memory notes."""
    from agents.memory import handle_memory_request
    response_text = await handle_memory_request(
        sender=state["sender"],
        sender_nickname=state.get("sender_nickname"),
        entities=state.get("entities", {}),
    )
    return {"response_text": response_text, "route_to": "direct"}


async def build_response(state: IntakeState) -> Dict[str, Any]:
    """Ensure we always have a response_text."""
    if state.get("response_text"):
        return {}

    intent = state.get("intent", IntentType.UNKNOWN)
    fallbacks = {
        IntentType.SCHEDULE:  "Voy a revisar el calendario ahora.",
        IntentType.LOGISTICS: "Calculo el tiempo de viaje y te aviso.",
        IntentType.SHOPPING:  "Listo, actualicé la lista.",
        IntentType.EXPENSE:   "Anotado el gasto.",
        IntentType.HOMEWORK:  "Anotada la tarea.",
        IntentType.MEMORY:    "Guardado.",
        IntentType.UNKNOWN:   "No entendí bien. ¿Podés reformular con más detalle?",
    }
    return {"response_text": fallbacks.get(intent, "Procesando tu solicitud…")}


async def determine_route(state: IntakeState) -> str:
    """Conditional edge: which node runs after classification."""
    intent = state.get("intent", IntentType.UNKNOWN)

    # LLM already provided a direct answer
    if state.get("response_text"):
        return "build_response"

    route_map = {
        IntentType.SHOPPING:  "handle_shopping",
        IntentType.SCHEDULE:  "handle_schedule",
        IntentType.LOGISTICS: "handle_logistics",
        IntentType.PLACES:    "handle_places",
        IntentType.EXPENSE:   "handle_expense",
        IntentType.HOMEWORK:  "handle_homework",
        IntentType.MEMORY:    "handle_memory",
        IntentType.UNKNOWN:   "build_response",
    }
    route = route_map.get(intent, "build_response")
    fallback = detect_fallback_route(state.get("raw_text", ""))
    if fallback == "shopping" and route == "build_response":
        route = "handle_shopping"
    elif fallback == "schedule" and route == "build_response":
        route = "handle_schedule"

    logger.info(
        "intake_route_selected",
        raw_text=state.get("raw_text", ""),
        intent=(intent or IntentType.UNKNOWN).value,
        entities=state.get("entities", {}),
        route=route,
        fallback=fallback,
    )
    return route
