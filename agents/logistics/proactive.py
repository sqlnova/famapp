"""Logistics Agent – proactive departure alerts using APScheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agents.logistics.maps_client import get_travel_time
from agents.schedule.calendar_client import get_events_in_window
from core.config import get_settings
from core.models import CalendarEvent
from core.supabase_client import get_supabase
from core.whatsapp import broadcast_whatsapp_message

logger = structlog.get_logger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


# ── Alert persistence ─────────────────────────────────────────────────────────

def _alert_already_scheduled(calendar_event_id: str) -> bool:
    """Return True if we already have an alert for this calendar event."""
    client = get_supabase()
    result = (
        client.table("logistics_alerts")
        .select("id")
        .eq("calendar_event_id", calendar_event_id)
        .execute()
    )
    return len(result.data) > 0


def _save_alert(
    event: CalendarEvent,
    scheduled_send: datetime,
    travel_minutes: int,
) -> None:
    s = get_settings()
    client = get_supabase()
    client.table("logistics_alerts").insert({
        "calendar_event_id": event.id,
        "destination": event.location,
        "scheduled_send": scheduled_send.isoformat(),
        "sent": False,
        "send_to": s.phone_list,
    }).execute()
    logger.info(
        "logistics_alert_saved",
        event=event.title,
        send_at=scheduled_send.isoformat(),
        travel_min=travel_minutes,
    )


def _mark_alert_sent(calendar_event_id: str) -> None:
    client = get_supabase()
    client.table("logistics_alerts").update({"sent": True}).eq(
        "calendar_event_id", calendar_event_id
    ).execute()


# ── Core logic ────────────────────────────────────────────────────────────────

async def _process_event(event: CalendarEvent) -> None:
    """For a single calendar event, calculate travel time and fire alert if needed."""
    if not event.location or not event.id:
        return

    if _alert_already_scheduled(event.id):
        logger.debug("logistics_alert_exists", event=event.title)
        return

    s = get_settings()
    now = datetime.now(timezone.utc)

    try:
        travel = get_travel_time(
            destination=event.location,
            departure_time=now,
        )
    except Exception:
        logger.exception("logistics_maps_error", event=event.title, location=event.location)
        return

    buffer = timedelta(minutes=s.logistics_buffer_minutes)
    travel_td = timedelta(minutes=travel.duration_minutes)
    leave_at = event.start - travel_td - buffer
    send_at = leave_at - timedelta(minutes=5)  # send alert 5 min before "leave" time

    if send_at <= now:
        # Too late to schedule – send immediately if leave_at is still in the future
        if leave_at > now:
            minutes_left = int((leave_at - now).total_seconds() / 60)
            _fire_alert(event, travel.duration_minutes, minutes_left)
            _save_alert(event, now, travel.duration_minutes)
        return

    # Schedule future alert
    _save_alert(event, send_at, travel.duration_minutes)
    logger.info("logistics_alert_scheduled", event=event.title, send_at=send_at.isoformat())


def _fire_alert(event: CalendarEvent, travel_minutes: int, leave_in_minutes: int) -> None:
    """Send the proactive WhatsApp departure alert."""
    travel_str = f"{travel_minutes} min" if travel_minutes < 60 else f"{travel_minutes // 60}h {travel_minutes % 60}min"
    if leave_in_minutes <= 0:
        time_phrase = "¡Ya tendrías que haber salido!"
    elif leave_in_minutes <= 5:
        time_phrase = "¡Salí ahora!"
    else:
        time_phrase = f"Salí en {leave_in_minutes} min"

    local_start = event.start.astimezone()
    event_time = local_start.strftime("%H:%M")

    msg = (
        f"🚗 *{time_phrase}*\n"
        f"📅 {event.title} a las {event_time}\n"
        f"📍 {event.location}\n"
        f"⏱ Tiempo de viaje: {travel_str} (con tráfico)"
    )
    broadcast_whatsapp_message(msg)
    logger.info("logistics_alert_fired", event=event.title, leave_in=leave_in_minutes)


# ── Scheduler job ─────────────────────────────────────────────────────────────

async def check_and_send_due_alerts() -> None:
    """Send any alerts whose scheduled_send time has passed."""
    client = get_supabase()
    now = datetime.now(timezone.utc)
    result = (
        client.table("logistics_alerts")
        .select("*")
        .eq("sent", False)
        .lte("scheduled_send", now.isoformat())
        .execute()
    )
    for row in result.data:
        try:
            # Re-fetch the calendar event details from the row data
            cal_event = CalendarEvent(
                id=row["calendar_event_id"],
                title=row.get("destination", "Evento"),  # fallback
                start=datetime.fromisoformat(row["scheduled_send"]),
                end=datetime.fromisoformat(row["scheduled_send"]),
                location=row["destination"],
            )
            send_to = row.get("send_to") or []
            travel_str = "calculado"
            msg = (
                f"🚗 *¡Es hora de salir!*\n"
                f"📍 {row['destination']}\n"
                f"⏱ Recordá salir con tiempo suficiente."
            )
            broadcast_whatsapp_message(msg, recipients=send_to if send_to else None)
            _mark_alert_sent(row["calendar_event_id"])
            logger.info("logistics_due_alert_sent", destination=row["destination"])
        except Exception:
            logger.exception("logistics_due_alert_error", row_id=row.get("id"))


async def poll_calendar_and_schedule() -> None:
    """Main scheduler job: check upcoming events and create alerts."""
    logger.info("logistics_scheduler_tick")
    try:
        s = get_settings()
        events = get_events_in_window(hours_ahead=s.logistics_lookahead_hours)
        for event in events:
            await _process_event(event)
        await check_and_send_due_alerts()
    except Exception:
        logger.exception("logistics_scheduler_error")


# ── Scheduler lifecycle ───────────────────────────────────────────────────────

def start_scheduler() -> AsyncIOScheduler:
    """Start the APScheduler. Call once on app startup."""
    global _scheduler
    s = get_settings()

    _scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")
    _scheduler.add_job(
        poll_calendar_and_schedule,
        trigger=IntervalTrigger(minutes=s.scheduler_interval_minutes),
        id="logistics_poll",
        name="Logistics: poll calendar & send alerts",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on start
    )
    _scheduler.start()
    logger.info("logistics_scheduler_started", interval_min=s.scheduler_interval_minutes)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("logistics_scheduler_stopped")
