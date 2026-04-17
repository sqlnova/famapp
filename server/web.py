"""Web interface – private family dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from uuid import uuid4

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agents.schedule.calendar_client import AR_TZ, create_event, delete_event, list_upcoming_events, update_event
from agents.logistics.maps_client import get_travel_time
from agents.tasks.suggestions import generate_task_suggestions, filter_duplicate_suggestions
from agents.intake.graph import intake_graph
from core.config import get_settings
from core.models import CalendarEvent, ShoppingItem
from core.privacy import mask_phone
from server.local_store import (
    delete_place as local_delete_place,
    list_places as local_list_places,
    list_routines as local_list_routines,
    save_place as local_save_place,
    save_routine as local_save_routine,
)
from core.supabase_client import (
    add_shopping_item,
    delete_known_place,
    get_all_known_places,
    get_completed_shopping_items,
    get_family_members,
    get_pending_shopping_items,
    get_supabase,
    get_known_places_dict,
    list_family_routines,
    resolve_place_address,
    mark_shopping_item_done,
    upsert_family_routine,
    upsert_known_place,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/app")
templates = Jinja2Templates(directory="server/templates", auto_reload=True)


def _allow_local_fallback() -> bool:
    """Allow local JSON fallback only outside production."""
    return not get_settings().is_production


def _list_places_from_tasks_store() -> List[Dict[str, Any]]:
    """Durable fallback storage backed by Supabase `tasks` table."""
    client = get_supabase()
    result = (
        client.table("tasks")
        .select("payload,status,triggered_by,created_at")
        .eq("agent", "known_place")
        .order("created_at", desc=True)
        .execute()
    )
    dedup: Dict[str, Dict[str, Any]] = {}
    for row in result.data:
        alias = (row.get("triggered_by") or "").strip().lower()
        if not alias or alias in dedup:
            continue
        if row.get("status") == "cancelled":
            dedup[alias] = {}
            continue
        payload = row.get("payload") or {}
        dedup[alias] = {
            "alias": alias,
            "name": payload.get("name") or alias,
            "address": payload.get("address") or "",
            "type": payload.get("type") or "general",
        }
    return [v for v in dedup.values() if v]


def _save_place_to_tasks_store(alias: str, name: str, address: str, place_type: str) -> Dict[str, Any]:
    client = get_supabase()
    clean = {
        "alias": (alias or "").strip().lower(),
        "name": (name or "").strip(),
        "address": (address or "").strip(),
        "type": (place_type or "general").strip().lower() or "general",
    }
    client.table("tasks").insert(
        {
            "agent": "known_place",
            "status": "done",
            "triggered_by": clean["alias"],
            "payload": clean,
        }
    ).execute()
    return clean


def _delete_place_from_tasks_store(alias: str) -> bool:
    key = (alias or "").strip().lower()
    if not key:
        return False
    client = get_supabase()
    client.table("tasks").insert(
        {
            "agent": "known_place",
            "status": "cancelled",
            "triggered_by": key,
            "payload": {"alias": key},
        }
    ).execute()
    return True


def _list_routines_from_tasks_store() -> List[Dict[str, Any]]:
    client = get_supabase()
    result = (
        client.table("tasks")
        .select("payload,triggered_by,created_at")
        .eq("agent", "family_routine")
        .eq("status", "done")
        .order("created_at", desc=True)
        .execute()
    )
    dedup: Dict[str, Dict[str, Any]] = {}
    for row in result.data:
        rid = str(row.get("triggered_by") or "").strip()
        if not rid or rid in dedup:
            continue
        payload = row.get("payload") or {}
        dedup[rid] = {
            "id": rid,
            "title": payload.get("title") or "Nueva rutina",
            "days": payload.get("days") or [],
            "children": payload.get("children") or [],
            "outbound_time": payload.get("outbound_time"),
            "return_time": payload.get("return_time"),
            "outbound_responsible": payload.get("outbound_responsible"),
            "return_responsible": payload.get("return_responsible"),
            "place_alias": payload.get("place_alias"),
            "place_name": payload.get("place_name"),
            "is_active": bool(payload.get("is_active", True)),
        }
    return list(dedup.values())


def _save_routine_to_tasks_store(clean_payload: Dict[str, Any]) -> Dict[str, Any]:
    client = get_supabase()
    rid = str(clean_payload["id"])
    client.table("tasks").insert(
        {
            "agent": "family_routine",
            "status": "done",
            "triggered_by": rid,
            "payload": clean_payload,
        }
    ).execute()
    return {
        "id": rid,
        "title": clean_payload["title"],
        "days": clean_payload["days"],
        "children": clean_payload["children"],
        "outbound_time": clean_payload["outbound_time"],
        "return_time": clean_payload["return_time"],
        "outbound_responsible": clean_payload["outbound_responsible"],
        "return_responsible": clean_payload["return_responsible"],
        "place_alias": clean_payload["place_alias"],
        "place_name": clean_payload["place_name"],
        "is_active": clean_payload["is_active"],
    }


def _suggest_departure(start: datetime, location: Optional[str]) -> str:
    """Suggest departure time using Maps traffic when available, fallback to -30m."""
    minutes_before = 30
    if location:
        try:
            known = get_known_places_dict()
            resolved = resolve_place_address(location, known)
            travel = get_travel_time(destination=resolved, departure_time=start.astimezone(timezone.utc))
            minutes_before = max(15, travel.duration_minutes + 10)
        except Exception:
            logger.info("maps_fallback_departure", location=location)
    leave = start - timedelta(minutes=minutes_before)
    return leave.astimezone(AR_TZ).isoformat()


def _suggest_departure_for_routine(time_str: str, location: Optional[str]) -> Optional[str]:
    """Calculate next departure time for a recurring routine.

    Rutinas se repiten día tras día, así que si la hora de hoy ya pasó,
    devolvemos la sugerencia para la próxima ocurrencia (mañana).
    """
    if not time_str or ":" not in time_str:
        return None
    try:
        h, m = map(int, time_str.split(':')[:2])
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        now = datetime.now(AR_TZ)
        action_time = now.replace(hour=h, minute=m, second=0, microsecond=0)

        # Si hoy ya pasó, correr a la próxima ocurrencia (mañana)
        if action_time <= now:
            action_time = action_time + timedelta(days=1)

        departure_iso = _suggest_departure(action_time, location)
        departure_time = datetime.fromisoformat(departure_iso)
        if departure_time <= now:
            return None
        return departure_iso
    except (ValueError, AttributeError, TypeError):
        return None


_ROUTINE_ID_TAG = "[routine_id:"


def _build_routine_event_description(routine_id: str, leg: str, routine_title: str) -> str:
    clean_leg = "outbound" if leg == "outbound" else "return"
    return f"[routine_id:{routine_id}]\n[routine_leg:{clean_leg}]\n[routine_title:{routine_title}]"


def _delete_existing_routine_mirror_events(routine_id: str) -> None:
    """Delete previously mirrored calendar events for a routine."""
    rid = (routine_id or "").strip()
    if not rid:
        return

    routine_tag = f"{_ROUTINE_ID_TAG}{rid}]"
    try:
        upcoming = list_upcoming_events(days=365, max_results=400)
    except Exception:
        logger.exception("routine_mirror_cleanup_list_failed", routine_id=rid)
        return

    for event in upcoming:
        if routine_tag not in (event.description or ""):
            continue
        if not event.id:
            continue
        try:
            delete_event(event.id)
        except Exception:
            logger.exception("routine_mirror_cleanup_delete_failed", routine_id=rid, event_id=event.id)


def _infer_user_nickname(user: Any) -> Optional[str]:
    """Best-effort map from auth email to family nickname."""
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email or "@" not in email:
        return None
    local = email.split("@", 1)[0]
    members = get_family_members()
    for member in members:
        nick = (member.nickname or "").strip().lower()
        if nick and (local == nick or local.startswith(f"{nick}.") or local.endswith(f".{nick}")):
            return nick
    return None


def _to_hhmm(raw: Optional[str], default: str) -> str:
    text = (raw or "").strip().lower().replace(".", ":")
    if not text:
        return default
    if text.endswith("hs"):
        text = text[:-2].strip()
    if ":" not in text:
        text = f"{text}:00"
    hh, mm = (text.split(":", 1) + ["00"])[:2]
    return f"{int(hh):02d}:{int(mm):02d}"


def _to_byday(days: List[str]) -> List[str]:
    mapping = {
        "lun": "MO", "lunes": "MO", "mo": "MO",
        "mar": "TU", "martes": "TU", "tu": "TU",
        "mie": "WE", "mié": "WE", "miercoles": "WE", "miércoles": "WE", "we": "WE",
        "jue": "TH", "jueves": "TH", "th": "TH",
        "vie": "FR", "viernes": "FR", "fr": "FR",
        "sab": "SA", "sáb": "SA", "sabado": "SA", "sábado": "SA", "sa": "SA",
        "dom": "SU", "domingo": "SU", "su": "SU",
    }
    out: List[str] = []
    for d in days:
        key = (d or "").strip().lower()
        val = mapping.get(key)
        if val and val not in out:
            out.append(val)
    return out


def _rrule_weekly(days: List[str]) -> Optional[str]:
    byday = _to_byday(days)
    if not byday:
        return None
    until = datetime.now(AR_TZ).replace(month=12, day=31, hour=23, minute=59, second=59).astimezone(timezone.utc)
    return f"RRULE:FREQ=WEEKLY;BYDAY={','.join(byday)};UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"


def _get_next_occurrence_date(days: List[str]) -> str:
    """Find the next date that matches one of the specified days of week.

    Args:
        days: List of day names (e.g., ["lunes", "jueves"])

    Returns:
        ISO date string for the next matching date
    """
    byday = _to_byday(days)
    if not byday:
        return datetime.now(AR_TZ).strftime("%Y-%m-%d")

    # Map RRULE day codes to Python weekday (0=Monday, 6=Sunday)
    day_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    target_weekdays = {day_map[code] for code in byday if code in day_map}

    # Start from today and find the next matching day
    current = datetime.now(AR_TZ)
    for _ in range(7):  # Check up to 7 days
        if current.weekday() in target_weekdays:
            return current.strftime("%Y-%m-%d")
        current += timedelta(days=1)

    # Fallback to today if nothing found (shouldn't happen with valid input)
    return datetime.now(AR_TZ).strftime("%Y-%m-%d")


# ── Auth ──────────────────────────────────────────────────────────────────────

async def require_auth(authorization: Optional[str] = Header(None)):
    """Verify Supabase JWT from Authorization: Bearer <token> header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.replace("Bearer ", "").strip()
    try:
        client = get_supabase()
        response = client.auth.get_user(token)
        if not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.user
    except HTTPException:
        raise
    except Exception:
        logger.warning("web_auth_failed")
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    s = get_settings()
    if not s.supabase_anon_key:
        return HTMLResponse(
            "<h2>Web UI no configurada. Agregá SUPABASE_ANON_KEY a las variables de entorno.</h2>",
            status_code=503,
        )
    response = templates.TemplateResponse("app.html", {
        "request": request,
        "supabase_url": s.supabase_url,
        "supabase_anon_key": s.supabase_anon_key,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


# ── API ───────────────────────────────────────────────────────────────────────

@router.get("/api/events")
async def api_events(user=Depends(require_auth), x_user_nickname: Optional[str] = Header(None)):
    loop = asyncio.get_event_loop()
    events = await loop.run_in_executor(None, lambda: list_upcoming_events(days=30))
    # Use nickname from header if provided, otherwise try to infer from email
    user_nickname = (x_user_nickname or "").strip().lower() if x_user_nickname else _infer_user_nickname(user)
    return [
        {
            "id": e.id,
            "title": e.title,
            "start": e.start.astimezone(AR_TZ).isoformat(),
            "end": e.end.astimezone(AR_TZ).isoformat(),
            "location": e.location,
            "responsible_nickname": e.responsible_nickname,
            "children": e.children,
            "recurring_event_id": e.recurring_event_id,
            "is_recurring": not e.alerts_enabled,
            "suggested_departure": _suggest_departure(e.start, e.location)
            if user_nickname and (e.responsible_nickname or "").strip().lower() == user_nickname
            else None,
        }
        for e in events
    ]


@router.post("/api/events")
async def api_create_event(
    payload: Dict[str, Any] = Body(...),
    user=Depends(require_auth),
):
    start_raw = payload.get("start")
    if not start_raw:
        raise HTTPException(status_code=400, detail="start es obligatorio")

    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha de inicio inválida") from exc

    end_raw = payload.get("end")
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Fecha de fin inválida") from exc
    else:
        end_dt = start_dt + timedelta(hours=1)

    event = CalendarEvent(
        id="",  # Will be assigned by Google Calendar
        title=payload.get("title", "Evento sin título"),
        start=start_dt,
        end=end_dt,
        location=payload.get("location", ""),
        responsible_nickname=payload.get("responsible_nickname", ""),
        children=payload.get("children") or [],
        description="",
        attendees=[],
        recurring_event_id=None,
    )

    created = create_event(event)
    return {
        "id": created.id,
        "recurring_event_id": created.recurring_event_id,
        "title": created.title,
        "start": created.start.astimezone(AR_TZ).isoformat(),
        "end": created.end.astimezone(AR_TZ).isoformat(),
        "location": created.location,
        "responsible_nickname": created.responsible_nickname,
        "children": created.children,
    }


@router.put("/api/events/{event_id}")
async def api_update_event(
    event_id: str,
    payload: Dict[str, Any] = Body(...),
    user=Depends(require_auth),
):
    start_raw = payload.get("start")
    if not start_raw:
        raise HTTPException(status_code=400, detail="start es obligatorio")

    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha de inicio inválida") from exc

    end_raw = payload.get("end")
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Fecha de fin inválida") from exc
    else:
        end_dt = start_dt + timedelta(hours=1)

    target_event_id = event_id
    if payload.get("apply_to_series") and payload.get("recurring_event_id"):
        target_event_id = str(payload["recurring_event_id"])

    updated = update_event(
        target_event_id,
        {
            "title": payload.get("title"),
            "start": start_dt,
            "end": end_dt,
            "location": payload.get("location"),
            "responsible_nickname": payload.get("responsible_nickname"),
            "children": payload.get("children") or [],
        },
    )
    return {
        "id": updated.id,
        "recurring_event_id": updated.recurring_event_id,
        "title": updated.title,
        "start": updated.start.astimezone(AR_TZ).isoformat(),
        "end": updated.end.astimezone(AR_TZ).isoformat(),
        "location": updated.location,
        "responsible_nickname": updated.responsible_nickname,
        "children": updated.children,
    }


@router.delete("/api/events/{event_id}")
async def api_delete_event(
    event_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    user=Depends(require_auth),
):
    payload = payload or {}
    target_event_id = event_id
    if payload.get("apply_to_series") and payload.get("recurring_event_id"):
        target_event_id = str(payload["recurring_event_id"])
    delete_event(target_event_id)
    return {"ok": True}


@router.get("/api/shopping")
async def api_shopping(user=Depends(require_auth)):
    pending, done = await asyncio.gather(get_pending_shopping_items(), get_completed_shopping_items())

    def serialize(items: List[ShoppingItem]) -> List[Dict[str, Any]]:
        return [
            {
                "id": str(i.id),
                "name": i.name,
                "quantity": i.quantity,
                "unit": i.unit,
                "done": i.done,
                "added_at": i.added_at.isoformat() if i.added_at else None,
            }
            for i in items
        ]

    return {"pending": serialize(pending), "done": serialize(done)}


@router.post("/api/shopping")
async def create_shopping_item(
    name: str = Body(...),
    quantity: str = Body(default=""),
    unit: str = Body(default=""),
    user=Depends(require_auth),
):
    item = ShoppingItem(
        name=name.strip(),
        quantity=quantity.strip() or None,
        unit=unit.strip() or None,
        added_by=(user.email or "web").strip(),
    )
    inserted = await add_shopping_item(item)
    return {
        "id": str(inserted.id),
        "name": inserted.name,
        "quantity": inserted.quantity,
        "unit": inserted.unit,
        "done": inserted.done,
    }


@router.put("/api/shopping/{item_id}/done")
async def mark_done(item_id: UUID, user=Depends(require_auth)):
    await mark_shopping_item_done(item_id)
    return {"ok": True}


@router.put("/api/shopping/{item_id}")
async def update_shopping(
    item_id: UUID,
    payload: Dict[str, Any] = Body(...),
    user=Depends(require_auth),
):
    client = get_supabase()
    update_payload = {
        "name": (payload.get("name") or "").strip(),
        "quantity": (payload.get("quantity") or "").strip() or None,
        "unit": (payload.get("unit") or "").strip() or None,
    }
    if not update_payload["name"]:
        raise HTTPException(status_code=400, detail="name es obligatorio")
    result = client.table("shopping_items").update(update_payload).eq("id", str(item_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return {"ok": True}


@router.delete("/api/shopping/{item_id}")
async def delete_shopping(item_id: UUID, user=Depends(require_auth)):
    client = get_supabase()
    result = client.table("shopping_items").delete().eq("id", str(item_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return {"ok": True}


@router.get("/api/family")
async def api_family(user=Depends(require_auth)):
    members = get_family_members()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "nickname": m.nickname,
            "role": "Menor" if m.is_minor else "Adulto",
            "phone": mask_phone(m.whatsapp_number),  # masked: never enviar número completo al browser
            "is_minor": m.is_minor,
        }
        for m in members
    ]


@router.put("/api/family/{member_id}/minor")
async def toggle_minor(member_id: UUID, is_minor: bool = Body(..., embed=True), user=Depends(require_auth)):
    client = get_supabase()
    client.table("family_members").update({"is_minor": is_minor}).eq("id", str(member_id)).execute()
    return {"ok": True}


@router.post("/api/family")
async def save_family_member(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name es obligatorio")

    nickname = (payload.get("nickname") or name).strip().lower().replace(" ", "_")
    raw_phone = (payload.get("phone") or "").strip()

    # Sólo actualizar el teléfono si se envía un número nuevo (sin enmascarar).
    # Un valor enmascarado contiene '*' y significa que el usuario no lo cambió.
    phone_is_new = bool(raw_phone) and "*" not in raw_phone
    if phone_is_new:
        whatsapp_number = raw_phone if raw_phone.startswith("whatsapp:") else f"whatsapp:{raw_phone}"
    else:
        whatsapp_number = None  # no actualizar

    member_id = payload.get("id")
    client = get_supabase()

    if member_id:
        # Update: sólo pisar los campos enviados; teléfono sólo si cambió
        update_data: Dict[str, Any] = {
            "name": name,
            "nickname": nickname,
            "is_minor": bool(payload.get("is_minor", False)),
        }
        if whatsapp_number is not None:
            update_data["whatsapp_number"] = whatsapp_number
        result = client.table("family_members").update(update_data).eq("id", member_id).execute()
    else:
        # Insert: teléfono obligatorio
        member_payload: Dict[str, Any] = {
            "name": name,
            "nickname": nickname,
            "whatsapp_number": whatsapp_number or "whatsapp:+540000000000",
            "is_minor": bool(payload.get("is_minor", False)),
        }
        result = client.table("family_members").insert(member_payload).execute()

    member = result.data[0]
    return {
        "id": member["id"],
        "name": member["name"],
        "nickname": member["nickname"],
        "phone": mask_phone(member["whatsapp_number"]),  # siempre enmascarado en respuesta
        "is_minor": member["is_minor"],
    }


@router.get("/api/tasks")
async def api_tasks(user=Depends(require_auth)):
    client = get_supabase()
    rows = (
        client.table("tasks")
        .select("*")
        .eq("agent", "family_task")
        .neq("status", "cancelled")
        .order("created_at", desc=True)
        .execute()
    )
    return [
        {
            "id": row["id"],
            "title": (row.get("payload") or {}).get("title"),
            "assignee": (row.get("payload") or {}).get("assignee"),
            "due_date": (row.get("payload") or {}).get("due_date"),
            "notes": (row.get("payload") or {}).get("notes"),
            "status": row.get("status", "pending"),
        }
        for row in rows.data
    ]


@router.post("/api/tasks")
async def create_task(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title es obligatorio")
    client = get_supabase()
    result = client.table("tasks").insert(
        {
            "agent": "family_task",
            "payload": {
                "title": title,
                "assignee": payload.get("assignee"),
                "due_date": payload.get("due_date"),
                "notes": payload.get("notes"),
            },
            "status": payload.get("status", "pending"),
        }
    ).execute()
    return {"id": result.data[0]["id"]}


@router.put("/api/tasks/{task_id}")
async def update_task(task_id: UUID, payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    client = get_supabase()
    data: Dict[str, Any] = {}
    if "status" in payload:
        data["status"] = payload["status"]
    if any(k in payload for k in ["title", "assignee", "due_date", "notes"]):
        data["payload"] = {
            "title": payload.get("title"),
            "assignee": payload.get("assignee"),
            "due_date": payload.get("due_date"),
            "notes": payload.get("notes"),
        }
    client.table("tasks").update(data).eq("id", str(task_id)).eq("agent", "family_task").execute()
    return {"ok": True}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: UUID, user=Depends(require_auth)):
    client = get_supabase()
    client.table("tasks").update({"status": "cancelled"}).eq("id", str(task_id)).eq("agent", "family_task").execute()
    return {"ok": True}


@router.post("/api/tasks/suggestions")
async def suggest_tasks(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    """Generate task suggestions based on an event's characteristics.

    Expects: event object with title, location, start, etc.
    Returns: list of suggested tasks that could help prepare for the event
    """
    event = CalendarEvent(**payload)
    suggestions = generate_task_suggestions(event)
    suggestions = filter_duplicate_suggestions(suggestions)
    return {"suggestions": suggestions}


@router.post("/api/agent/chat")
async def chat_with_agent(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    """Run FamApp's Intake agent from the private web UI."""
    raw_message = (payload.get("message") or "").strip()
    if not raw_message:
        raise HTTPException(status_code=400, detail="message es obligatorio")

    sender = (getattr(user, "email", None) or "web_user").strip().lower()
    initial_state = {
        "messages": [],
        "raw_text": raw_message,
        "sender": f"web:{sender}",
        "intent": None,
        "confidence": 0.0,
        "entities": {},
        "summary": "",
        "route_to": None,
        "response_text": None,
        "message_sid": f"web-{uuid4()}",
    }
    try:
        final_state = await intake_graph.ainvoke(initial_state)
    except Exception as error:
        logger.exception("web_agent_chat_failed", error=str(error))
        raise HTTPException(status_code=500, detail="No se pudo procesar el mensaje en este momento.") from error

    response_text = (
        (final_state.get("response_text") or "").strip()
        or "Todavía no pude resolver eso. ¿Querés que lo intentemos con más detalle?"
    )
    return {
        "reply": response_text,
        "intent": str(final_state.get("intent").value) if final_state.get("intent") else "unknown",
        "confidence": float(final_state.get("confidence") or 0.0),
        "route_to": final_state.get("route_to") or "direct",
        "entities": final_state.get("entities") or {},
        "summary": final_state.get("summary") or "",
    }


# ── Places ────────────────────────────────────────────────────────────────────

@router.get("/api/places")
async def api_places(user=Depends(require_auth)):
    rows: List[Dict[str, Any]] = []
    try:
        places = get_all_known_places()
        rows = [{"alias": p.alias, "name": p.name, "address": p.address, "type": p.place_type or "general"} for p in places]
    except Exception as error:
        logger.warning("places_db_read_failed", error=str(error))
        try:
            rows = _list_places_from_tasks_store()
        except Exception as fallback_error:
            logger.warning("places_tasks_fallback_read_failed", error=str(fallback_error))
            if not _allow_local_fallback():
                raise HTTPException(status_code=503, detail="No se pudo leer lugares desde la base de datos.")

    if _allow_local_fallback():
        local_rows = local_list_places()
        if local_rows:
            seen = {(r["alias"] or "").lower() for r in rows}
            rows.extend([r for r in local_rows if (r.get("alias") or "").lower() not in seen])
    try:
        tasks_rows = _list_places_from_tasks_store()
        if tasks_rows:
            seen = {(r["alias"] or "").lower() for r in rows}
            rows.extend([r for r in tasks_rows if (r.get("alias") or "").lower() not in seen])
    except Exception:
        logger.debug("places_tasks_fallback_merge_skipped")
    if rows:
        return rows

    # Fallback: if known_places is empty, expose places referenced by routines
    try:
        routines = list_family_routines()
    except Exception:
        routines = []
    derived = []
    seen = set()
    for r in routines:
        alias = (r.place_alias or r.place_name or "").strip().lower()
        name = (r.place_name or r.place_alias or "").strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        derived.append(
            {
                "alias": alias,
                "name": name or alias,
                "address": "",
                "type": "general",
            }
        )
    return derived


@router.post("/api/places")
async def save_place(
    alias: str = Body(...),
    name: str = Body(...),
    address: str = Body(...),
    place_type: str = Body(default="general", embed=False),
    user=Depends(require_auth),
):
    try:
        place = upsert_known_place(alias, name, address, place_type)
        return {"alias": place.alias, "name": place.name, "address": place.address, "type": place.place_type}
    except Exception as error:
        logger.warning("places_db_write_failed", error=str(error))
        try:
            logger.warning("places_db_write_using_tasks_fallback")
            return _save_place_to_tasks_store(alias, name, address, place_type)
        except Exception as fallback_error:
            logger.warning("places_tasks_fallback_write_failed", error=str(fallback_error))
            if _allow_local_fallback():
                logger.warning("places_db_write_fallback_local_enabled")
                return local_save_place({"alias": alias, "name": name, "address": address, "type": place_type})
            raise HTTPException(status_code=503, detail="No se pudo guardar el lugar en la base de datos.")


@router.delete("/api/places/{alias}")
async def remove_place(alias: str, user=Depends(require_auth)):
    try:
        deleted = delete_known_place(alias)
    except Exception:
        deleted = False
    if not deleted:
        try:
            deleted = _delete_place_from_tasks_store(alias)
        except Exception:
            deleted = False
    local_deleted = local_delete_place(alias)
    if not deleted and not local_deleted:
        raise HTTPException(status_code=404, detail="Lugar no encontrado")
    return {"ok": True}


# ── Routines ──────────────────────────────────────────────────────────────────

@router.get("/api/routines")
async def api_routines(user=Depends(require_auth), x_user_nickname: Optional[str] = Header(None)):
    routines = []
    try:
        routines = list_family_routines()
    except Exception as error:
        logger.warning("routines_db_read_failed", error=str(error))
        try:
            routines = _list_routines_from_tasks_store()
            if _allow_local_fallback():
                local_rows = local_list_routines()
                if local_rows:
                    seen = {str(r["id"]) for r in routines}
                    routines.extend([r for r in local_rows if str(r.get("id")) not in seen])
        except Exception as fallback_error:
            logger.warning("routines_tasks_fallback_read_failed", error=str(fallback_error))
            if not _allow_local_fallback():
                raise HTTPException(status_code=503, detail="No se pudo leer rutinas desde la base de datos.")
            routines = local_list_routines()

    # Use nickname from header if provided, otherwise try to infer from email
    user_nickname = (x_user_nickname or "").strip().lower() if x_user_nickname else _infer_user_nickname(user)
    rows = []
    seen = set()

    for r in routines:
        # Handle both model objects and dictionaries
        is_dict = isinstance(r, dict)
        r_id = str(r.get("id") if is_dict else r.id)
        if r_id in seen:
            continue
        seen.add(r_id)

        place_name = r.get("place_name") if is_dict else r.place_name
        place_alias = r.get("place_alias") if is_dict else r.place_alias
        location = place_name or place_alias

        row = {
            "id": r_id,
            "title": r.get("title") if is_dict else r.title,
            "days": r.get("days") if is_dict else r.days,
            "children": (r.get("children") or []) if is_dict else (r.children or []),
            "outbound_time": r.get("outbound_time") if is_dict else r.outbound_time,
            "return_time": r.get("return_time") if is_dict else r.return_time,
            "outbound_responsible": r.get("outbound_responsible") if is_dict else r.outbound_responsible,
            "return_responsible": r.get("return_responsible") if is_dict else r.return_responsible,
            "place_alias": place_alias,
            "place_name": place_name,
            "is_active": r.get("is_active", True) if is_dict else r.is_active,
        }
        # Calculate suggested departure times if user is responsible
        if user_nickname:
            outbound_resp = (row.get("outbound_responsible") or "").strip().lower()
            return_resp = (row.get("return_responsible") or "").strip().lower()
            if outbound_resp == user_nickname:
                row["suggested_departure_outbound"] = _suggest_departure_for_routine(row.get("outbound_time"), location)
            if return_resp == user_nickname:
                row["suggested_departure_return"] = _suggest_departure_for_routine(row.get("return_time"), location)
        rows.append(row)

    return rows


@router.post("/api/routines")
async def api_save_routine(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    is_new = not payload.get("id")

    # Validate required fields
    title = (payload.get("title") or "Nueva rutina").strip()
    days = payload.get("days") or []

    if not days:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un día de la semana")

    if is_new and not (payload.get("outbound_time") or payload.get("return_time")):
        raise HTTPException(status_code=400, detail="Debe especificar hora de ida o vuelta")

    clean_payload = {
        "id": payload.get("id") or str(uuid4()),
        "title": title,
        "days": days,
        "children": payload.get("children") or [],
        "outbound_time": payload.get("outbound_time") or None,
        "return_time": payload.get("return_time") or None,
        "outbound_responsible": payload.get("outbound_responsible") or None,
        "return_responsible": payload.get("return_responsible") or None,
        "place_alias": payload.get("place_alias") or None,
        "place_name": payload.get("place_name") or None,
        "is_active": payload.get("is_active", True),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    routine_obj: Dict[str, Any]
    try:
        routine = upsert_family_routine(clean_payload)
        routine_obj = {
            "id": str(routine.id),
            "title": routine.title,
            "days": routine.days,
            "children": routine.children or [],
            "outbound_time": routine.outbound_time,
            "return_time": routine.return_time,
            "outbound_responsible": routine.outbound_responsible,
            "return_responsible": routine.return_responsible,
            "place_alias": routine.place_alias,
            "place_name": routine.place_name,
            "is_active": routine.is_active,
        }
    except Exception as first_error:
        logger.warning("routine_upsert_full_failed", error=str(first_error))
        # Backward-compatible fallback for older DB schemas missing newer columns.
        fallback_payload = {
            "id": clean_payload["id"],
            "title": clean_payload["title"],
            "days": clean_payload["days"],
            "outbound_time": clean_payload["outbound_time"],
            "return_time": clean_payload["return_time"],
            "outbound_responsible": clean_payload["outbound_responsible"],
            "return_responsible": clean_payload["return_responsible"],
            "place_alias": clean_payload["place_alias"],
            "place_name": clean_payload["place_name"],
            "is_active": clean_payload["is_active"],
        }
        try:
            routine = upsert_family_routine(fallback_payload)
            routine_obj = {
                "id": str(routine.id),
                "title": routine.title,
                "days": routine.days,
                "children": routine.children or [],
                "outbound_time": routine.outbound_time,
                "return_time": routine.return_time,
                "outbound_responsible": routine.outbound_responsible,
                "return_responsible": routine.return_responsible,
                "place_alias": routine.place_alias,
                "place_name": routine.place_name,
                "is_active": routine.is_active,
            }
        except Exception as second_error:
            logger.warning("routine_upsert_fallback_failed", error=str(second_error))
            try:
                logger.warning("routine_upsert_using_tasks_fallback")
                routine_obj = _save_routine_to_tasks_store(clean_payload)
            except Exception as fallback_error:
                logger.warning("routine_tasks_fallback_write_failed", error=str(fallback_error))
                if _allow_local_fallback():
                    logger.warning("routine_upsert_local_fallback_enabled")
                    routine_obj = local_save_routine(clean_payload)
                else:
                    raise HTTPException(status_code=503, detail="No se pudo guardar la rutina en la base de datos.")

    try:
        rrule = _rrule_weekly(routine_obj["days"])
        if rrule:
            routine_id = str(routine_obj.get("id") or "")
            if routine_id:
                _delete_existing_routine_mirror_events(routine_id)

            place_label = routine_obj["place_name"] or routine_obj["place_alias"] or "actividad"
            known_places = {p.alias: p for p in get_all_known_places()}
            location = resolve_place_address(routine_obj["place_alias"] or routine_obj["place_name"] or "", known_places) or routine_obj["place_name"]
            children = routine_obj["children"] or []
            people = ", ".join(children) if children else "los chicos"
            start_date = _get_next_occurrence_date(routine_obj["days"])

            if routine_obj["outbound_time"]:
                t0 = _to_hhmm(routine_obj["outbound_time"], "07:30")
                start0 = AR_TZ.localize(datetime.fromisoformat(f"{start_date}T{t0}:00"))
                event0 = CalendarEvent(
                    title=f"Llevar a {people} al {place_label}",
                    start=start0,
                    end=start0 + timedelta(minutes=15),
                    location=location,
                    responsible_nickname=routine_obj["outbound_responsible"],
                    children=children,
                    description=_build_routine_event_description(routine_id, "outbound", routine_obj["title"]),
                )
                create_event(event0, recurrence=[rrule])
            if routine_obj["return_time"]:
                t1 = _to_hhmm(routine_obj["return_time"], "12:00")
                start1 = AR_TZ.localize(datetime.fromisoformat(f"{start_date}T{t1}:00"))
                event1 = CalendarEvent(
                    title=f"Buscar a {people} del {place_label}",
                    start=start1,
                    end=start1 + timedelta(minutes=15),
                    location=location,
                    responsible_nickname=routine_obj["return_responsible"],
                    children=children,
                    description=_build_routine_event_description(routine_id, "return", routine_obj["title"]),
                )
                create_event(event1, recurrence=[rrule])
    except Exception:
        logger.exception("routine_mirror_events_failed", is_new=is_new, routine_id=routine_obj.get("id"))

    return routine_obj


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.get("/api/expenses")
async def api_get_expenses(days: int = 30, user=Depends(require_auth)):
    from core.supabase_client import get_expenses
    expenses = get_expenses(days=days)
    return [
        {
            "id": str(e.id) if e.id else None,
            "description": e.description,
            "amount": e.amount,
            "category": e.category,
            "paid_by": e.paid_by,
            "expense_date": e.expense_date,
        }
        for e in expenses
    ]


@router.post("/api/expenses")
async def api_add_expense(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    from core.models import Expense
    from core.supabase_client import add_expense
    from agents.expenses import _categorize_expense

    amount_raw = payload.get("amount")
    try:
        amount = float(str(amount_raw).replace(",", ".").replace("$", "").strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Monto inválido")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")

    description = (payload.get("description") or "").strip()
    category = payload.get("category") or _categorize_expense(description)
    expense = Expense(
        description=description or "Gasto",
        amount=amount,
        category=category,
        paid_by=payload.get("paid_by") or None,
        expense_date=payload.get("expense_date") or None,
        notes=payload.get("notes") or None,
    )
    saved = add_expense(expense)
    return {"id": str(saved.id), "ok": True}


# ── Homework ──────────────────────────────────────────────────────────────────

@router.get("/api/homework")
async def api_get_homework(child: Optional[str] = None, user=Depends(require_auth)):
    from core.supabase_client import get_pending_homework
    tasks = get_pending_homework(child)
    return [
        {
            "id": str(t.id) if t.id else None,
            "child_name": t.child_name,
            "subject": t.subject,
            "description": t.description,
            "due_date": t.due_date,
            "done": t.done,
        }
        for t in tasks
    ]


@router.post("/api/homework")
async def api_add_homework(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    from core.models import HomeworkTask
    from core.supabase_client import add_homework_task

    child_name = (payload.get("child_name") or "").strip()
    description = (payload.get("description") or "").strip()
    due_date = (payload.get("due_date") or "").strip()
    if not child_name or not description or not due_date:
        raise HTTPException(status_code=400, detail="child_name, description y due_date son obligatorios")

    task = HomeworkTask(
        child_name=child_name,
        subject=(payload.get("subject") or "General").strip(),
        description=description,
        due_date=due_date,
        added_by=None,
    )
    saved = add_homework_task(task)
    return {"id": str(saved.id), "ok": True}


@router.put("/api/homework/{task_id}/done")
async def api_homework_done(task_id: str, user=Depends(require_auth)):
    from core.supabase_client import mark_homework_done
    mark_homework_done(task_id)
    return {"ok": True}


# ── Family Memory ─────────────────────────────────────────────────────────────

@router.get("/api/memory")
async def api_get_memory(subject: Optional[str] = None, user=Depends(require_auth)):
    from core.supabase_client import get_family_notes
    notes = get_family_notes(subject)
    return [
        {
            "id": str(n.id) if n.id else None,
            "subject": n.subject,
            "note": n.note,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


@router.post("/api/memory")
async def api_add_memory(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    from core.models import FamilyNote
    from core.supabase_client import add_family_note

    note_text = (payload.get("note") or "").strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note es obligatorio")

    note = FamilyNote(
        subject=(payload.get("subject") or "general").strip().lower(),
        note=note_text,
        added_by=None,
    )
    saved = add_family_note(note)
    return {"id": str(saved.id), "ok": True}


@router.delete("/api/memory/{note_id}")
async def api_delete_memory(note_id: str, user=Depends(require_auth)):
    from core.supabase_client import get_supabase
    client = get_supabase()
    result = client.table("family_notes").delete().eq("id", note_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    return {"ok": True}
