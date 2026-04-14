"""Unit tests for Intake routing and shopping flow (no real LLM or DB calls)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agents.intake.state import IntakeState
from core.models import IntentType


def make_state(**kwargs) -> IntakeState:
    defaults: IntakeState = {
        "messages": [],
        "raw_text": "hola",
        "sender": "whatsapp:+5491100000000",
        "intent": None,
        "confidence": 0.0,
        "entities": {},
        "summary": "",
        "route_to": None,
        "response_text": None,
        "message_sid": "SM123",
    }
    defaults.update(kwargs)
    return defaults


def test_determine_route_shopping_intent():
    from agents.intake.nodes import determine_route

    result = asyncio.run(determine_route(make_state(intent=IntentType.SHOPPING, response_text=None)))
    assert result == "handle_shopping"


def test_determine_route_schedule_intent():
    from agents.intake.nodes import determine_route

    result = asyncio.run(determine_route(make_state(intent=IntentType.SCHEDULE, response_text=None)))
    assert result == "handle_schedule"


def test_determine_route_unknown_shopping_fallback():
    from agents.intake.nodes import determine_route

    result = asyncio.run(determine_route(make_state(intent=IntentType.UNKNOWN, raw_text="yogurt", response_text=None)))
    assert result == "handle_shopping"


def test_build_response_unknown_fallback():
    from agents.intake.nodes import build_response

    result = asyncio.run(build_response(make_state(intent=IntentType.UNKNOWN, response_text=None)))
    assert "reformular" in result["response_text"].lower()


def test_parse_and_classify_shopping():
    from agents.intake.nodes import parse_and_classify

    mock_response = MagicMock()
    mock_response.content = '{"intent":"shopping","confidence":0.95,"entities":{"items":[{"name":"leche","quantity":"2","unit":"litros"}]},"summary":"Agregar leche","response":null}'

    with patch("agents.intake.nodes._get_llm") as mock_llm_factory:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        state = make_state(raw_text="Agregá 2 litros de leche a la lista")
        result = asyncio.run(parse_and_classify(state))

    assert result["intent"] == IntentType.SHOPPING
    assert result["entities"]["items"][0]["name"] == "leche"


def test_handle_shopping_parses_single_word_and_dedupes():
    from agents.intake.nodes import handle_shopping

    state = make_state(raw_text="agrega leche y leche", intent=IntentType.SHOPPING, entities={"action": "add", "items": []})

    with patch("agents.intake.tools.add_shopping_item", new=AsyncMock()) as add_mock:
        result = asyncio.run(handle_shopping(state))

    assert result["route_to"] == "direct"
    assert "leche" in result["response_text"].lower()
    assert add_mock.await_count == 1


def test_incoming_whatsapp_sender_phone_strips_prefix():
    from core.models import IncomingWhatsAppMessage

    msg = IncomingWhatsAppMessage(
        MessageSid="SM1",
        From="whatsapp:+5491100000000",
        To="whatsapp:+14155238886",
        Body="test",
    )
    assert msg.sender_phone == "+5491100000000"
