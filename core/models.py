"""Shared Pydantic domain models."""
from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    SCHEDULE = "schedule"       # "agendame una reunión"
    LOGISTICS = "logistics"     # "a qué hora salgo para llegar a tiempo"
    SHOPPING = "shopping"       # "agregá leche a la lista"
    PLACES = "places"           # "el colegio es en Av. X 123"
    EXPENSE = "expense"         # "anoté $8500 en el súper"
    HOMEWORK = "homework"       # "Giuseppe tiene que entregar la maqueta el viernes"
    MEMORY = "memory"           # "Gaetano no come mariscos" / "qué recordás de Giuseppe?"
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
    recurring_event_id: Optional[str] = None
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)
    responsible_nickname: Optional[str] = None  # slug from family_members table
    children: List[str] = Field(default_factory=list)
    recurrence: List[str] = Field(default_factory=list)
    alerts_enabled: bool = True  # False for recurring instances (no alert spam)


# ── Family ────────────────────────────────────────────────────────────────────

class FamilyMember(BaseModel):
    id: Optional[UUID] = None
    name: str              # display: "Papá", "Mamá"
    nickname: str          # slug used in events: "papa", "mama"
    whatsapp_number: str   # whatsapp:+54911...
    is_minor: bool = False # True for children → "llevar + retirar" rule applies


class KnownPlace(BaseModel):
    id: Optional[UUID] = None
    alias: str    # short key: "colegio", "club", "supermercado"
    name: str     # display name: "Club Regatas Resistencia"
    address: str  # full address for Google Maps
    place_type: Optional[str] = "general"


class FamilyRoutine(BaseModel):
    id: Optional[UUID] = None
    title: str
    days: List[str] = Field(default_factory=list)
    children: Optional[List[str]] = None
    outbound_time: Optional[str] = None
    return_time: Optional[str] = None
    outbound_responsible: Optional[str] = None
    return_responsible: Optional[str] = None
    place_alias: Optional[str] = None
    place_name: Optional[str] = None
    is_active: bool = True


# ── Shopping ──────────────────────────────────────────────────────────────────

class ShoppingItem(BaseModel):
    id: Optional[UUID] = None
    name: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    added_by: Optional[str] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)
    done: bool = False
    category: str = "Otros"
    times_purchased: int = 0


# ── Expenses ──────────────────────────────────────────────────────────────────

class Expense(BaseModel):
    id: Optional[UUID] = None
    description: str
    amount: float
    category: str = "General"
    paid_by: Optional[str] = None        # nickname
    expense_date: Optional[str] = None   # YYYY-MM-DD
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Homework ──────────────────────────────────────────────────────────────────

class HomeworkTask(BaseModel):
    id: Optional[UUID] = None
    child_name: str
    subject: str = "General"
    description: str
    due_date: str                        # YYYY-MM-DD
    done: bool = False
    added_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Family Memory ─────────────────────────────────────────────────────────────

class FamilyNote(BaseModel):
    id: Optional[UUID] = None
    subject: str = "general"
    note: str
    added_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


# ── Logistics Domain ──────────────────────────────────────────────────────────
# Core primitives for the family logistics copilot. A CalendarEvent is raw
# input; a LogisticsBlock is the operational unit the planner works with.

class LogisticsBlockKind(str, Enum):
    PICKUP = "pickup"     # retirar / buscar / pasar a buscar
    DROP = "drop"         # llevar / dejar
    STAY = "stay"         # permanecer en el lugar (clase, partido)
    ERRAND = "errand"     # mandado / trámite
    UNKNOWN = "unknown"


class ConflictKind(str, Enum):
    TEMPORAL_PERSON = "temporal_person"     # misma persona en dos bloques solapados
    SPATIAL = "spatial"                     # no hay nadie que pueda cubrir ambos
    TRAVEL_INFEASIBLE = "travel_infeasible"  # no alcanza el tiempo para viajar
    DRIVER = "driver"                       # asignado no puede conducir / no apto
    ORPHAN_MINOR = "orphan_minor"            # menor queda sin adulto responsable


class ConflictSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class PlanStatus(str, Enum):
    CALMA = "calma"
    OCUPADO = "ocupado"
    REVISAR = "revisar"


class SupportRole(str, Enum):
    CORE = "core"           # adulto del núcleo (papá / mamá)
    GRANDPARENT = "grandparent"
    NANNY = "nanny"
    NEIGHBOR = "neighbor"
    CARPOOL = "carpool"
    OTHER = "other"


class SupportNetworkMember(BaseModel):
    """Tercero de confianza que puede cubrir logística puntualmente.

    Complementa a FamilyMember (núcleo) con red extendida: abuelos, nannies,
    vecinos, carpools. Tiene nivel de confianza y tipos de tarea permitidos.
    """
    id: Optional[UUID] = None
    name: str
    nickname: str
    role: SupportRole = SupportRole.OTHER
    can_drive: bool = True
    allowed_kinds: List[LogisticsBlockKind] = Field(default_factory=list)
    allowed_children: List[str] = Field(default_factory=list)  # nicknames
    trust_level: float = Field(0.5, ge=0.0, le=1.0)
    contactable_via: Optional[str] = None   # whatsapp / phone / none
    notes: Optional[str] = None


class AvailabilityWindow(BaseModel):
    """Ventana en la que un responsable puede cubrir logística."""
    id: Optional[UUID] = None
    member_nickname: str
    weekday: int = Field(ge=0, le=6)   # 0 = lunes
    start: time
    end: time
    hard: bool = True   # hard = no-negociable; soft = preferencia


class RoutineException(BaseModel):
    """Excepción puntual a una FamilyRoutine (p.ej. esta semana no hay club)."""
    id: Optional[UUID] = None
    routine_id: UUID
    date: str                           # YYYY-MM-DD
    skip: bool = True
    override_responsible: Optional[str] = None
    notes: Optional[str] = None


class LogisticsBlock(BaseModel):
    """Unidad operativa del planificador.

    Un bloque representa una acción logística concreta (llevar, retirar,
    permanecer) con lugar, ventana de tiempo y miembros involucrados. Puede
    provenir de 1..N eventos de calendario (resultado de una fusión).
    """
    id: UUID = Field(default_factory=uuid4)
    kind: LogisticsBlockKind = LogisticsBlockKind.UNKNOWN
    title: str
    start: datetime
    end: datetime
    location_alias: Optional[str] = None     # key en KnownPlace
    location_name: Optional[str] = None
    members: List[str] = Field(default_factory=list)   # chicos involucrados
    responsible: Optional[str] = None                  # nickname adulto
    source_event_ids: List[str] = Field(default_factory=list)
    merged_from: List[UUID] = Field(default_factory=list)  # bloques fusionados
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    needs_review: bool = False
    notes: Optional[str] = None

    @property
    def duration_minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))


class Trip(BaseModel):
    """Traslado físico que materializa uno o varios LogisticsBlock."""
    id: UUID = Field(default_factory=uuid4)
    origin: Optional[str] = None           # alias o dirección
    destination: str
    depart_at: datetime
    arrive_at: datetime
    driver_nickname: Optional[str] = None
    passenger_members: List[str] = Field(default_factory=list)
    block_ids: List[UUID] = Field(default_factory=list)
    estimated_travel_minutes: Optional[int] = None
    combined: bool = False                 # True si agrupa ≥2 bloques


class Conflict(BaseModel):
    """Problema detectado por el motor."""
    id: UUID = Field(default_factory=uuid4)
    kind: ConflictKind
    severity: ConflictSeverity = ConflictSeverity.WARNING
    block_ids: List[UUID] = Field(default_factory=list)
    involved_members: List[str] = Field(default_factory=list)
    reason_code: str = ""
    explanation: str = ""
    suggested_resolutions: List[str] = Field(default_factory=list)


class Assignment(BaseModel):
    """Resultado de asignar un responsable a un bloque."""
    block_id: UUID
    responsible_nickname: str
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    reason_code: str = ""
    explanation: str = ""
    alternatives: List[Tuple[str, float]] = Field(default_factory=list)


class DailyPlan(BaseModel):
    """Salida principal del motor de planificación."""
    id: UUID = Field(default_factory=uuid4)
    date: str                              # YYYY-MM-DD
    status: PlanStatus = PlanStatus.CALMA
    feasibility_score: float = Field(1.0, ge=0.0, le=1.0)
    blocks: List[LogisticsBlock] = Field(default_factory=list)
    trips: List[Trip] = Field(default_factory=list)
    conflicts: List[Conflict] = Field(default_factory=list)
    assignments: List[Assignment] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    summary_es: Optional[str] = None


class PlanFeedbackAction(str, Enum):
    ACCEPT = "accept"
    OVERRIDE = "override"
    EDIT = "edit"
    IGNORE = "ignore"


class PlanFeedback(BaseModel):
    """Señal de aprendizaje: qué hizo el usuario con el plan."""
    id: Optional[UUID] = None
    plan_id: UUID
    block_id: Optional[UUID] = None
    user_nickname: str
    action: PlanFeedbackAction
    delta: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PreferenceProfile(BaseModel):
    """Afinidad histórica aprendida (responsable × lugar × tipo de bloque)."""
    id: Optional[UUID] = None
    member_nickname: str
    place_alias: Optional[str] = None
    block_kind: Optional[LogisticsBlockKind] = None
    weekday: Optional[int] = None
    score: float = Field(0.5, ge=0.0, le=1.0)
    sample_size: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
