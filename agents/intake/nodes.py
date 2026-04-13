"""Intake Agent – LangGraph node implementations."""
from __future__ import annotations

import json
from typing import Any, Dict

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.config import get_settings
from core.models import IntentType
from agents.intake.state import IntakeState

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
                   Ejemplos: "¿qué tengo mañana?", "¿qué hay esta semana?", "agendame el dentista", "¿cuándo es el cumple de mamá?"
   - "logistics" : tiempo de viaje, a qué hora salir, tráfico, cómo llegar.
                   Ejemplos: "¿cuánto tardo en llegar a Palermo?", "¿a qué hora salgo para llegar a tiempo?"
   - "shopping"  : lista de compras — agregar, consultar o tachar items.
                   Ejemplos: "agregá leche", "¿qué falta comprar?", "comprar pan y huevos",
                             "tachá la leche", "ya compré el pan", "marca el aceite como comprado"
   - "unknown"   : no podés determinar la intención con certeza

   IMPORTANTE: Nunca uses "unknown" si el mensaje claramente habla de calendario, viajes o compras.
   La categoría "query" NO EXISTE — toda consulta cae en schedule, logistics o shopping según el tema.

2. Extraer ENTIDADES según la intención:
   - schedule  → { "title": str, "date": str, "time": str, "location": str, "people": [str] }
   - logistics → { "destination": str, "event_time": str, "origin": str }
   - shopping  → {
       "action": "add" | "list" | "mark_done",
       "items": [{"name": str, "quantity": str, "unit": str}]
     }
     Para "mark_done" los items contienen solo el nombre de lo que ya se compró.

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


async def parse_and_classify(state: IntakeState) -> Dict[str, Any]:
    """LLM call to parse intent and extract entities."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=state["raw_text"]),
    ]
    logger.info("intake_parsing", sender=state["sender"], text=state["raw_text"][:100])
    response = await llm.ainvoke(messages)
    content = response.content

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}

    intent_str = parsed.get("intent", "unknown")
    try:
        intent = IntentType(intent_str)
    except ValueError:
        intent = IntentType.UNKNOWN

    logger.info("intake_classified", intent=intent, confidence=parsed.get("confidence", 0.0))

    return {
        "messages": state["messages"] + [HumanMessage(content=state["raw_text"]), response],
        "intent": intent,
        "confidence": float(parsed.get("confidence", 0.0)),
        "entities": parsed.get("entities", {}),
        "summary": parsed.get("summary", ""),
        "response_text": parsed.get("response"),
    }


async def handle_shopping(state: IntakeState) -> Dict[str, Any]:
    """Process shopping requests within Intake."""
    from agents.intake.tools import add_item_to_shopping_list, list_shopping_items, mark_items_done

    entities = state.get("entities", {})
    action = entities.get("action", "")
    items = entities.get("items", [])

    if action == "mark_done" and items:
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

    return {"response_text": response_text, "route_to": "direct"}


async def handle_schedule(state: IntakeState) -> Dict[str, Any]:
    """Delegate to the Schedule Agent (Google Calendar)."""
    from agents.schedule.nodes import handle_schedule as schedule_handler
    response_text = await schedule_handler(
        sender=state["sender"],
        raw_text=state["raw_text"],
        entities=state.get("entities", {}),
    )
    return {"response_text": response_text, "route_to": "schedule"}


async def handle_logistics(state: IntakeState) -> Dict[str, Any]:
    """Delegate to the Logistics Agent (Google Maps)."""
    from agents.logistics import handle_logistics_query
    response_text = await handle_logistics_query(
        sender=state["sender"],
        entities=state.get("entities", {}),
        message_sid=state["message_sid"],
    )
    return {"response_text": response_text, "route_to": "logistics"}


async def build_response(state: IntakeState) -> Dict[str, Any]:
    """Ensure we always have a response_text."""
    if state.get("response_text"):
        return {}

    intent = state.get("intent", IntentType.UNKNOWN)
    fallbacks = {
        IntentType.SCHEDULE:  "Voy a revisar el calendario ahora.",
        IntentType.LOGISTICS: "Calculo el tiempo de viaje y te aviso.",
        IntentType.SHOPPING:  "Listo, actualicé la lista.",
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
        IntentType.UNKNOWN:   "build_response",
    }
    return route_map.get(intent, "build_response")
