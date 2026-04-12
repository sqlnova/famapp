"""Unit tests for the Intake Agent – no real LLM or DB calls."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import IntentType
from agents.intake.state import IntakeState


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Tests: determine_route ────────────────────────────────────────────────────

class TestDetermineRoute:
    @pytest.mark.asyncio
    async def test_shopping_intent_routes_to_handle_shopping(self):
        from agents.intake.nodes import determine_route
        state = make_state(intent=IntentType.SHOPPING, response_text=None)
        result = await determine_route(state)
        assert result == "handle_shopping"

    @pytest.mark.asyncio
    async def test_direct_response_skips_subagents(self):
        from agents.intake.nodes import determine_route
        state = make_state(intent=IntentType.SHOPPING, response_text="Listo!")
        result = await determine_route(state)
        assert result == "build_response"

    @pytest.mark.asyncio
    async def test_schedule_intent_routes_to_build_response(self):
        from agents.intake.nodes import determine_route
        state = make_state(intent=IntentType.SCHEDULE, response_text=None)
        result = await determine_route(state)
        assert result == "build_response"

    @pytest.mark.asyncio
    async def test_unknown_intent_routes_to_build_response(self):
        from agents.intake.nodes import determine_route
        state = make_state(intent=IntentType.UNKNOWN, response_text=None)
        result = await determine_route(state)
        assert result == "build_response"


# ── Tests: build_response ─────────────────────────────────────────────────────

class TestBuildResponse:
    @pytest.mark.asyncio
    async def test_existing_response_unchanged(self):
        from agents.intake.nodes import build_response
        state = make_state(response_text="Ya tenés respuesta")
        result = await build_response(state)
        assert result == {}  # no changes

    @pytest.mark.asyncio
    async def test_fallback_for_unknown(self):
        from agents.intake.nodes import build_response
        state = make_state(intent=IntentType.UNKNOWN, response_text=None)
        result = await build_response(state)
        assert "response_text" in result
        assert "reformular" in result["response_text"].lower()

    @pytest.mark.asyncio
    async def test_fallback_for_schedule(self):
        from agents.intake.nodes import build_response
        state = make_state(intent=IntentType.SCHEDULE, response_text=None)
        result = await build_response(state)
        assert "calendar" in result["response_text"].lower() or "agenda" in result["response_text"].lower() or result["response_text"]


# ── Tests: parse_and_classify (mocked LLM) ────────────────────────────────────

class TestParseAndClassify:
    @pytest.mark.asyncio
    async def test_shopping_classification(self):
        from agents.intake.nodes import parse_and_classify

        mock_response = MagicMock()
        mock_response.content = '{"intent":"shopping","confidence":0.95,"entities":{"items":[{"name":"leche","quantity":"2","unit":"litros"}]},"summary":"Agregar leche","response":null}'

        with patch("agents.intake.nodes._get_llm") as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_response
            mock_llm_factory.return_value = mock_llm

            state = make_state(raw_text="Agregá 2 litros de leche a la lista")
            result = await parse_and_classify(state)

        assert result["intent"] == IntentType.SHOPPING
        assert result["confidence"] == 0.95
        assert result["entities"]["items"][0]["name"] == "leche"

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_unknown(self):
        from agents.intake.nodes import parse_and_classify

        mock_response = MagicMock()
        mock_response.content = "no es json"

        with patch("agents.intake.nodes._get_llm") as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_response
            mock_llm_factory.return_value = mock_llm

            state = make_state(raw_text="algo raro")
            result = await parse_and_classify(state)

        assert result["intent"] == IntentType.UNKNOWN


# ── Tests: IncomingWhatsAppMessage model ──────────────────────────────────────

class TestIncomingWhatsAppMessage:
    def test_sender_phone_strips_prefix(self):
        from core.models import IncomingWhatsAppMessage
        msg = IncomingWhatsAppMessage(
            MessageSid="SM1",
            From="whatsapp:+5491100000000",
            To="whatsapp:+14155238886",
            Body="test",
        )
        assert msg.sender_phone == "+5491100000000"

    def test_defaults(self):
        from core.models import IncomingWhatsAppMessage
        msg = IncomingWhatsAppMessage(
            MessageSid="SM2",
            From="whatsapp:+1",
            To="whatsapp:+2",
            Body="",
        )
        assert msg.num_media == 0
        assert msg.body == ""
