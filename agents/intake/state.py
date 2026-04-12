"""Intake Agent – LangGraph state definition."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage

from core.models import IntentType


class IntakeState(TypedDict):
    # Conversation history (LangGraph standard)
    messages: List[BaseMessage]

    # Inbound message
    raw_text: str
    sender: str           # whatsapp:+XXXXXXXXXX

    # Parsed by LLM
    intent: Optional[IntentType]
    confidence: float
    entities: Dict[str, Any]
    summary: str

    # Routing + response
    route_to: Optional[str]   # 'schedule' | 'logistics' | 'shopping' | 'direct'
    response_text: Optional[str]

    # DB record tracking
    message_sid: str
