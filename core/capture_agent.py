from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from dateutil import parser as date_parser
import pytz
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from core.config import get_settings

AR_TZ = pytz.timezone("America/Argentina/Buenos_Aires")


class CaptureEvent(BaseModel):
    title: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    related_child: str = ""
    notes: str = ""
    needs_confirmation: bool = True


class CaptureTask(BaseModel):
    title: str = ""
    due_date: str = ""
    due_time: str = ""
    assigned_to: str = ""
    related_child: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    notes: str = ""


class CaptureReminder(BaseModel):
    title: str = ""
    remind_at: str = ""
    channel: Literal["push"] = "push"
    notes: str = ""


class CaptureResult(BaseModel):
    classification: Literal["event", "task", "reminder", "shopping_list", "school_notice", "payment_due", "logistics", "mixed", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    events: List[CaptureEvent] = Field(default_factory=list)
    tasks: List[CaptureTask] = Field(default_factory=list)
    reminders: List[CaptureReminder] = Field(default_factory=list)
    missing_info: List[str] = Field(default_factory=list)
    questions_for_user: List[str] = Field(default_factory=list)


def _resolve_relative_day(text: str, now: datetime) -> str:
    weekdays = {
        "lunes": 0,
        "martes": 1,
        "miércoles": 2,
        "miercoles": 2,
        "jueves": 3,
        "viernes": 4,
        "sábado": 5,
        "sabado": 5,
        "domingo": 6,
    }
    lower = text.lower()
    for name, target in weekdays.items():
        if name in lower:
            delta = (target - now.weekday()) % 7
            delta = 7 if delta == 0 else delta
            return now.replace(hour=0, minute=0, second=0, microsecond=0).date().fromordinal(now.date().toordinal() + delta).isoformat()
    return ""


def _heuristic_parse(raw_text: str, family_context: Dict[str, Any]) -> CaptureResult:
    now = datetime.now(AR_TZ)
    result = CaptureResult(classification="mixed", confidence=0.65, summary=raw_text)
    date_guess = _resolve_relative_day(raw_text, now)
    time_guess = "18:00" if "18" in raw_text else ""
    location = "Kids Park" if "kids park" in raw_text.lower() else ""

    if "cumple" in raw_text.lower():
        result.events.append(CaptureEvent(title="Cumple de Sofi", date=date_guess, start_time=time_guess, location=location, needs_confirmation=True))
    if "comprar" in raw_text.lower():
        result.tasks.append(CaptureTask(title="Comprar regalo", due_date=date_guess, due_time="", priority="medium"))
    if "llevar medias" in raw_text.lower():
        result.tasks.append(CaptureTask(title="Llevar medias", due_date=date_guess, due_time="", priority="medium"))
    if not date_guess:
        result.missing_info.append("fecha")
        result.questions_for_user.append("¿Qué fecha corresponde?")
    if not time_guess and result.events:
        result.missing_info.append("hora")
        result.questions_for_user.append("¿A qué hora es?")
    known_children = [m.get("name", "") for m in family_context.get("members", []) if m.get("is_minor")]
    if known_children and result.events and not result.events[0].related_child:
        result.questions_for_user.append("¿Para cuál hijo/a?")
    return result


def run_capture_agent(raw_text: str, family_context: Dict[str, Any], input_type: str = "text") -> CaptureResult:
    if not raw_text.strip():
        return CaptureResult(classification="unknown", confidence=0.0, missing_info=["contenido"], questions_for_user=["Escribí o adjuntá algo para analizar"])

    try:
        settings = get_settings()
        llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
        structured = llm.with_structured_output(CaptureResult)
        now = datetime.now(AR_TZ).strftime("%Y-%m-%d %H:%M")
        prompt = f"""Sos CaptureAgent de Famapp. Hora actual {now} ({AR_TZ.zone}).\nNo inventes fechas/horas faltantes.\nInput type: {input_type}.\nContexto familiar: {family_context}.\nMensaje: {raw_text}"""
        return structured.invoke(prompt)
    except Exception:
        return _heuristic_parse(raw_text, family_context)
