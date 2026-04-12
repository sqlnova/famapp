"""Intake Agent – LangGraph graph definition and runner."""
from __future__ import annotations

from typing import Optional

import structlog
from langgraph.graph import END, START, StateGraph

from agents.intake.nodes import (
    build_response,
    determine_route,
    handle_shopping,
    parse_and_classify,
)
from agents.intake.state import IntakeState
from core.models import IntentType, MessageStatus
from core.supabase_client import update_message_status
from core.whatsapp import send_whatsapp_message

logger = structlog.get_logger(__name__)


def build_intake_graph() -> StateGraph:
    """Construct and compile the Intake Agent graph."""
    graph = StateGraph(IntakeState)

    # ── Nodes ────────────────────────────────────────────────────
    graph.add_node("parse_and_classify", parse_and_classify)
    graph.add_node("handle_shopping", handle_shopping)
    graph.add_node("build_response", build_response)

    # ── Edges ────────────────────────────────────────────────────
    graph.add_edge(START, "parse_and_classify")

    # Conditional routing after classification
    graph.add_conditional_edges(
        "parse_and_classify",
        determine_route,
        {
            "handle_shopping": "handle_shopping",
            "build_response":  "build_response",
        },
    )

    graph.add_edge("handle_shopping", "build_response")
    graph.add_edge("build_response", END)

    return graph.compile()


# Compiled graph (module-level singleton)
intake_graph = build_intake_graph()


async def run_intake(
    message_sid: str,
    sender: str,
    raw_text: str,
) -> Optional[str]:
    """Run the intake graph for a single incoming message.

    Returns the response text to send back to the user.
    """
    initial_state: IntakeState = {
        "messages": [],
        "raw_text": raw_text,
        "sender": sender,
        "intent": None,
        "confidence": 0.0,
        "entities": {},
        "summary": "",
        "route_to": None,
        "response_text": None,
        "message_sid": message_sid,
    }

    try:
        await update_message_status(message_sid, MessageStatus.PROCESSING)

        final_state = await intake_graph.ainvoke(initial_state)
        response_text: Optional[str] = final_state.get("response_text")

        await update_message_status(
            message_sid,
            MessageStatus.RESPONDED,
            response=response_text,
            intent=final_state.get("intent"),
            entities=final_state.get("entities"),
        )

        if response_text:
            send_whatsapp_message(sender, response_text)
            logger.info("intake_response_sent", sender=sender, intent=final_state.get("intent"))

        return response_text

    except Exception:
        logger.exception("intake_graph_error", message_sid=message_sid)
        await update_message_status(message_sid, MessageStatus.FAILED)
        error_msg = "Ocurrió un error procesando tu mensaje. Intentá de nuevo."
        send_whatsapp_message(sender, error_msg)
        return error_msg
