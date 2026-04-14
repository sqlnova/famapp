"""Web interface – private family dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agents.schedule.calendar_client import AR_TZ, delete_event, list_upcoming_events, update_event
from agents.logistics.maps_client import get_travel_time
from core.config import get_settings
from core.models import ShoppingItem
from core.supabase_client import (
    add_shopping_item,
    delete_known_place,
    get_all_known_places,
    get_completed_shopping_items,
    get_family_members,
    get_pending_shopping_items,
    get_supabase,
    list_family_routines,
    mark_shopping_item_done,
    upsert_family_routine,
    upsert_known_place,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/app")
templates = Jinja2Templates(directory="server/templates")


def _suggest_departure(start: datetime, location: Optional[str]) -> str:
    """Suggest departure time using Maps traffic when available, fallback to -30m."""
    minutes_before = 30
    if location:
        try:
            travel = get_travel_time(destination=location, departure_time=start.astimezone(timezone.utc))
            minutes_before = max(15, travel.duration_minutes + 10)
        except Exception:
            logger.info("maps_fallback_departure", location=location)
    leave = start - timedelta(minutes=minutes_before)
    return leave.astimezone(AR_TZ).isoformat()


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
    return templates.TemplateResponse("app.html", {
        "request": request,
        "supabase_url": s.supabase_url,
        "supabase_anon_key": s.supabase_anon_key,
    })


# ── API ───────────────────────────────────────────────────────────────────────

@router.get("/api/events")
async def api_events(user=Depends(require_auth)):
    loop = asyncio.get_event_loop()
    events = await loop.run_in_executor(None, lambda: list_upcoming_events(days=30))
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
            "suggested_departure": _suggest_departure(e.start, e.location),
        }
        for e in events
    ]


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
            "phone": m.whatsapp_number.replace("whatsapp:", ""),
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
    whatsapp_number = (payload.get("phone") or "").strip()
    if whatsapp_number and not whatsapp_number.startswith("whatsapp:"):
        whatsapp_number = f"whatsapp:{whatsapp_number}"

    member_payload = {
        "name": name,
        "nickname": nickname,
        "whatsapp_number": whatsapp_number or "whatsapp:+540000000000",
        "is_minor": bool(payload.get("is_minor", False)),
    }
    if payload.get("id"):
        member_payload["id"] = payload["id"]

    client = get_supabase()
    result = client.table("family_members").upsert(member_payload).execute()
    member = result.data[0]
    return {
        "id": member["id"],
        "name": member["name"],
        "nickname": member["nickname"],
        "phone": member["whatsapp_number"].replace("whatsapp:", ""),
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


# ── Places ────────────────────────────────────────────────────────────────────

@router.get("/api/places")
async def api_places(user=Depends(require_auth)):
    places = get_all_known_places()
    return [{"alias": p.alias, "name": p.name, "address": p.address, "type": p.place_type or "general"} for p in places]


@router.post("/api/places")
async def save_place(
    alias: str = Body(...),
    name: str = Body(...),
    address: str = Body(...),
    place_type: str = Body(default="general", embed=False),
    user=Depends(require_auth),
):
    place = upsert_known_place(alias, name, address, place_type)
    return {"alias": place.alias, "name": place.name, "address": place.address, "type": place.place_type}


@router.delete("/api/places/{alias}")
async def remove_place(alias: str, user=Depends(require_auth)):
    deleted = delete_known_place(alias)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lugar no encontrado")
    return {"ok": True}


# ── Routines ──────────────────────────────────────────────────────────────────

@router.get("/api/routines")
async def api_routines(user=Depends(require_auth)):
    routines = list_family_routines()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "days": r.days,
            "outbound_time": r.outbound_time,
            "return_time": r.return_time,
            "outbound_responsible": r.outbound_responsible,
            "return_responsible": r.return_responsible,
            "place_alias": r.place_alias,
            "place_name": r.place_name,
            "is_active": r.is_active,
        }
        for r in routines
    ]


@router.post("/api/routines")
async def api_save_routine(payload: Dict[str, Any] = Body(...), user=Depends(require_auth)):
    clean_payload = {
        "id": payload.get("id"),
        "title": (payload.get("title") or "Nueva rutina").strip(),
        "days": payload.get("days") or [],
        "outbound_time": payload.get("outbound_time") or None,
        "return_time": payload.get("return_time") or None,
        "outbound_responsible": payload.get("outbound_responsible") or None,
        "return_responsible": payload.get("return_responsible") or None,
        "place_alias": payload.get("place_alias") or None,
        "place_name": payload.get("place_name") or None,
        "is_active": payload.get("is_active", True),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if not clean_payload["id"]:
        clean_payload.pop("id")
    routine = upsert_family_routine(clean_payload)
    return {
        "id": str(routine.id),
        "title": routine.title,
        "days": routine.days,
        "outbound_time": routine.outbound_time,
        "return_time": routine.return_time,
        "outbound_responsible": routine.outbound_responsible,
        "return_responsible": routine.return_responsible,
        "place_alias": routine.place_alias,
        "place_name": routine.place_name,
        "is_active": routine.is_active,
    }
