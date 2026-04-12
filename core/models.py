"""Shared Pydantic domain models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    SCHEDULE = "schedule"       # "agendame una reunión"
    LOGISTICS = "logistics"     # "a qué hora salgo para llegar a tiempo"
    SHOPPING = "shopping"       # "agregá leche a la lista"
    QUERY = "query"             # "qué tengo mañana?"
    UNKNOWN = "unknown"


class MessageStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    RESPONDED = "responded"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


# ── WhatsApp ──────────────────────────────────────────────────────────────────

class IncomingWhatsAppMessage(BaseModel):
    """Parsed Twilio webhook payload for an incoming WhatsApp message."""
    message_sid: str = Field(..., alias="MessageSid")
    from_number: str = Field(..., alias="From")      # whatsapp:+5491100000000
    to_number: str = Field(..., alias="To")
    body: str = Field("", alias="Body")
    num_media: int = Field(0, alias="NumMedia")
    media_url: Optional[str] = Field(None, alias="MediaUrl0")
    profile_name: Optional[str] = Field(None, alias="ProfileName")

    model_config = {"populate_by_name": True}

    @property
    def sender_phone(self) -> str:
        """Return raw phone number without 'whatsapp:' prefix."""
        return self.from_number.replace("whatsapp:", "")


# ── Intake / Routing ──────────────────────────────────────────────────────────

class ParsedIntent(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: Dict[str, Any] = Field(default_factory=dict)
    summary: str = Field("", description="Brief human-readable summary of what was understood")


class AgentMessage(BaseModel):
    """Internal message passed between agents."""
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sender: str
    raw_text: str
    parsed: Optional[ParsedIntent] = None
    response: Optional[str] = None


# ── Calendar ──────────────────────────────────────────────────────────────────

class CalendarEvent(BaseModel):
    id: Optional[str] = None
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)


# ── Shopping ──────────────────────────────────────────────────────────────────

class ShoppingItem(BaseModel):
    id: Optional[UUID] = None
    name: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    added_by: Optional[str] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)
    done: bool = False


# ── DB record ─────────────────────────────────────────────────────────────────

class MessageRecord(BaseModel):
    """Row in messages table."""
    id: Optional[UUID] = None
    message_sid: str
    from_number: str
    body: str
    intent: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    response: Optional[str] = None
    status: MessageStatus = MessageStatus.RECEIVED
    created_at: datetime = Field(default_factory=datetime.utcnow)
