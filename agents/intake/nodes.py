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

# ── Shared LLM instance ───────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.openai_model,
        api_key=s.openai_api_key,
        temperature=0,
    )


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos el agente de recepción (Intake) de FamApp, un sistema familiar de logística.
Tu tarea es analizar mensajes de WhatsApp de miembros de la familia y:

1. Clasificar la INTENCIÓN principal del mensaje en una de estas categorías:
   - "schedule"  : quieren agendar, modificar o consultar un evento en el calendario
   - "logistics" : quieren saber a qué hora salir, cuánto tarda un viaje, alertas de tráfico
   - "shopping"  : quieren agregar o consultar la lista de compras
   - "query"     : consulta general (¿qué tengo mañana?, ¿quién lleva a los chicos?)
   - "unknown"   : no podés determinar la intención

2. Extraer ENTIDADES relevantes según la intención:
   - schedule  → { "title": str, "date": str, "time": str, "location": str, "people": [str] }
   - logistics → { "destination": str, "event_time": str, "origin": str }
   - shopping  → { "items": [{"name": str, "quantity": str, "unit": str}] }
   - query     → { "topic": str }

3. Responder SIEMPRE en español rioplatense informal y breve.

Devolvé SIEMPRE un JSON con este esquema exacto (sin markdown):
{
  "intent": "<intención>",
  "confidence": <0.0-1.0>,
  "entities": { ... },
  "summary": "<resumen breve en español>",
  "response": "<respuesta directa al usuario si podés resolverlo aquí, o null si hay que derivar>"
}
"""


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def parse_and_classify(state: IntakeState) -> Dict[str, Any]:
    """Call LLM to parse intent and extract entities from the incoming message."""
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
        # Try to extract JSON block if LLM wrapped it
        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}

    intent_str = parsed.get("intent", "unknown")
    try:
        intent = IntentType(intent_str)
    except ValueError:
        intent = IntentType.UNKNOWN

    logger.info(
        "intake_classified",
        intent=intent,
        confidence=parsed.get("confidence", 0.0),
        summary=parsed.get("summary", ""),
    )

    return {
        "messages": state["messages"] + [HumanMessage(content=state["raw_text"]), response],
        "intent": intent,
        "confidence": float(parsed.get("confidence", 0.0)),
        "entities": parsed.get("entities", {}),
        "summary": parsed.get("summary", ""),
        "response_text": parsed.get("response"),  # May be None – means we need to route
    }


async def handle_shopping(state: IntakeState) -> Dict[str, Any]:
    """Process shopping requests directly within Intake."""
    from agents.intake.tools import add_item_to_shopping_list, list_shopping_items

    entities = state.get("entities", {})
    items = entities.get("items", [])
    responses = []

    if items:
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
        # Query for current list
        response_text = await list_shopping_items.ainvoke({})

    return {"response_text": response_text, "route_to": "direct"}


async def build_response(state: IntakeState) -> Dict[str, Any]:
    """Final node: ensure we have a response_text ready to send."""
    if state.get("response_text"):
        return {}

    # Fallback: acknowledge and inform that it's being processed
    intent = state.get("intent", IntentType.UNKNOWN)
    fallbacks = {
        IntentType.SCHEDULE:  "Entendido, voy a gestionar eso en el calendario ahora.",
        IntentType.LOGISTICS: "Ok, calculo el tiempo de viaje y te aviso.",
        IntentType.SHOPPING:  "Listo, actualicé la lista de compras.",
        IntentType.QUERY:     "Déjame consultar y te respondo en un momento.",
        IntentType.UNKNOWN:   "No entendí bien. ¿Podés reformular?",
    }
    return {"response_text": fallbacks.get(intent, "Procesando tu solicitud…")}


async def determine_route(state: IntakeState) -> str:
    """Conditional edge: decide which node to go to next."""
    intent = state.get("intent", IntentType.UNKNOWN)
    response = state.get("response_text")

    # If LLM already produced a direct response, skip sub-agents
    if response:
        return "build_response"

    route_map = {
        IntentType.SHOPPING:  "handle_shopping",
        IntentType.SCHEDULE:  "build_response",   # stub → will call Schedule Agent later
        IntentType.LOGISTICS: "build_response",   # stub → will call Logistics Agent later
        IntentType.QUERY:     "build_response",
        IntentType.UNKNOWN:   "build_response",
    }
    return route_map.get(intent, "build_response")
