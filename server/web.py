"""Web interface – private family dashboard."""
from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agents.schedule.calendar_client import AR_TZ, list_upcoming_events
from core.config import get_settings
from core.supabase_client import (
    delete_known_place,
    get_all_known_places,
    get_family_members,
    get_pending_shopping_items,
    get_supabase,
    mark_shopping_item_done,
    upsert_known_place,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/app")
templates = Jinja2Templates(directory="server/templates")


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
    events = await loop.run_in_executor(None, lambda: list_upcoming_events(days=14))
    return [
        {
            "id": e.id,
            "title": e.title,
            "start": e.start.astimezone(AR_TZ).isoformat(),
            "end": e.end.astimezone(AR_TZ).isoformat(),
            "location": e.location,
            "responsible_nickname": e.responsible_nickname,
            "is_recurring": not e.alerts_enabled,
        }
        for e in events
    ]


@router.get("/api/shopping")
async def api_shopping(user=Depends(require_auth)):
    items = await get_pending_shopping_items()
    return [
        {
            "id": str(i.id),
            "name": i.name,
            "quantity": i.quantity,
            "unit": i.unit,
        }
        for i in items
    ]


@router.put("/api/shopping/{item_id}/done")
async def mark_done(item_id: UUID, user=Depends(require_auth)):
    await mark_shopping_item_done(item_id)
    return {"ok": True}


@router.get("/api/family")
async def api_family(user=Depends(require_auth)):
    members = get_family_members()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "nickname": m.nickname,
            "whatsapp_number": m.whatsapp_number.replace("whatsapp:", ""),
            "is_minor": m.is_minor,
        }
        for m in members
    ]


@router.put("/api/family/{member_id}/minor")
async def toggle_minor(member_id: UUID, is_minor: bool = Body(..., embed=True), user=Depends(require_auth)):
    client = get_supabase()
    client.table("family_members").update({"is_minor": is_minor}).eq("id", str(member_id)).execute()
    return {"ok": True}


# ── Places ────────────────────────────────────────────────────────────────────

@router.get("/api/places")
async def api_places(user=Depends(require_auth)):
    places = get_all_known_places()
    return [{"alias": p.alias, "name": p.name, "address": p.address} for p in places]


@router.post("/api/places")
async def save_place(
    alias: str = Body(...),
    name: str = Body(...),
    address: str = Body(...),
    user=Depends(require_auth),
):
    place = upsert_known_place(alias, name, address)
    return {"alias": place.alias, "name": place.name, "address": place.address}


@router.delete("/api/places/{alias}")
async def remove_place(alias: str, user=Depends(require_auth)):
    deleted = delete_known_place(alias)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lugar no encontrado")
    return {"ok": True}
