"""Logistics Agent – proactive departure alerts using APScheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agents.logistics.maps_client import get_travel_time
from agents.schedule.calendar_client import AR_TZ, get_events_in_window
from core.config import get_settings
from core.models import CalendarEvent
from core.supabase_client import get_family_member_by_nickname, get_supabase
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


def _resolve_responsible_whatsapp(event: CalendarEvent) -> Optional[str]:
    """Return the WhatsApp number of the event's responsible person, or None."""
    if not event.responsible_nickname:
        return None
    try:
        member = get_family_member_by_nickname(event.responsible_nickname)
        return member.whatsapp_number if member else None
    except Exception:
        logger.warning("responsible_lookup_failed", nickname=event.responsible_nickname)
        return None


def _save_alert(
    event: CalendarEvent,
    scheduled_send: datetime,
    travel_minutes: int,
    leave_at: datetime,
    responsible_whatsapp: Optional[str] = None,
) -> None:
    from core.whatsapp import _get_broadcast_recipients
    client = get_supabase()
    client.table("logistics_alerts").insert({
        "calendar_event_id": event.id,
        "event_title": event.title,
        "event_start_utc": event.start.astimezone(timezone.utc).isoformat(),
        "destination": event.location,
        "scheduled_send": scheduled_send.isoformat(),
        "travel_minutes": travel_minutes,
        "leave_at_utc": leave_at.astimezone(timezone.utc).isoformat(),
        "sent": False,
        "send_to": _get_broadcast_recipients(),
        "responsible_whatsapp": responsible_whatsapp,
    }).execute()
    logger.info(
        "logistics_alert_saved",
        event=event.title,
        send_at=scheduled_send.isoformat(),
        leave_at=leave_at.isoformat(),
        travel_min=travel_minutes,
    )


def _mark_alert_sent(calendar_event_id: str) -> None:
    client = get_supabase()
    client.table("logistics_alerts").update({"sent": True}).eq(
        "calendar_event_id", calendar_event_id
    ).execute()


# ── Core logic ────────────────────────────────────────────────────────────────

async def schedule_manual_alert(event: CalendarEvent) -> str:
    """Schedule a departure alert for any event, bypassing the alerts_enabled flag.

    Used when the user explicitly requests a reminder for a recurring event instance.
    Returns a human-readable confirmation or error message.
    """
    if not event.location:
        return f"El evento *{event.title}* no tiene dirección guardada, no puedo calcular el tiempo de viaje."

    if not event.id:
        return "No pude identificar el evento en el calendario."

    if _alert_already_scheduled(event.id):
        local = event.start.astimezone(AR_TZ)
        return f"Ya tenés una alerta agendada para *{event.title}* el {local.strftime('%-d/%-m a las %H:%M')}."

    s = get_settings()
    now = datetime.now(timezone.utc)
    responsible_wa = _resolve_responsible_whatsapp(event)

    try:
        travel = get_travel_time(destination=event.location, departure_time=now)
    except Exception:
        logger.exception("manual_alert_maps_error", event=event.title, location=event.location)
        return f"No pude calcular el tiempo de viaje a '{event.location}'. Intentá de nuevo."

    travel_td = timedelta(minutes=travel.duration_minutes)
    leave_at = event.start - travel_td
    prep_buffer = timedelta(minutes=s.logistics_buffer_minutes)
    send_at = leave_at - prep_buffer

    local_event = event.start.astimezone(AR_TZ)
    local_leave = leave_at.astimezone(AR_TZ)
    local_alert = send_at.astimezone(AR_TZ)

    if send_at <= now:
        if leave_at > now:
            minutes_left = int((leave_at - now).total_seconds() / 60)
            _fire_alert(event, travel.duration_minutes, minutes_left, responsible_wa)
            _save_alert(event, now, travel.duration_minutes, leave_at, responsible_wa)
            return (
                f"✅ *¡Alerta enviada ahora!*\n"
                f"📅 {event.title} a las {local_event.strftime('%H:%M')}\n"
                f"🕐 Tenés que salir en {minutes_left} min"
            )
        return f"Ya pasó la hora de salir para *{event.title}*."

    _save_alert(event, send_at, travel.duration_minutes, leave_at, responsible_wa)
    logger.info("manual_alert_scheduled", event=event.title, send_at=send_at.isoformat())
    return (
        f"✅ Te aviso a las *{local_alert.strftime('%H:%M')}*\n"
        f"📅 {event.title} · {local_event.strftime('%-d/%-m a las %H:%M')}\n"
        f"🕐 Salís a las {local_leave.strftime('%H:%M')} · ⏱ {travel.duration_minutes} min de tráfico"
    )


async def _process_event(event: CalendarEvent) -> None:
    """For a single calendar event, calculate travel time and fire alert if needed."""
    if not event.location or not event.id:
        return
    # Recurring instances each have a unique event.id (e.g. base_id_YYYYMMDDTHHMMSSZ),
    # so _alert_already_scheduled() already prevents duplicates within the same occurrence.
    if _alert_already_scheduled(event.id):
        logger.debug("logistics_alert_exists", event=event.title)
        return

    s = get_settings()
    now = datetime.now(timezone.utc)
    responsible_wa = _resolve_responsible_whatsapp(event)

    try:
        travel = get_travel_time(
            destination=event.location,
            departure_time=now,
        )
    except Exception:
        logger.exception("logistics_maps_error", event=event.title, location=event.location)
        return

    travel_td = timedelta(minutes=travel.duration_minutes)
    # leave_at = the exact moment they must walk out the door to arrive on time
    leave_at = event.start - travel_td
    # send_at = leave_at minus prep time (getting ready, reading the message, etc.)
    prep_buffer = timedelta(minutes=s.logistics_buffer_minutes)
    send_at = leave_at - prep_buffer

    if send_at <= now:
        # Too late to schedule – send immediately if departure is still ahead
        if leave_at > now:
            minutes_left = int((leave_at - now).total_seconds() / 60)
            _fire_alert(event, travel.duration_minutes, minutes_left, responsible_wa)
            _save_alert(event, now, travel.duration_minutes, leave_at, responsible_wa)
        return

    # Schedule future alert
    _save_alert(event, send_at, travel.duration_minutes, leave_at, responsible_wa)
    logger.info("logistics_alert_scheduled", event=event.title, send_at=send_at.isoformat())


def _fire_alert(
    event: CalendarEvent,
    travel_minutes: int,
    leave_in_minutes: int,
    responsible_wa: Optional[str] = None,
) -> None:
    """Send the proactive WhatsApp departure alert to the responsible person (or everyone)."""
    travel_str = (
        f"{travel_minutes} min"
        if travel_minutes < 60
        else f"{travel_minutes // 60}h {travel_minutes % 60}min"
    )
    if leave_in_minutes <= 0:
        time_phrase = "¡Ya tendrías que haber salido!"
    elif leave_in_minutes <= 5:
        time_phrase = "¡Salí ahora!"
    else:
        time_phrase = f"Salí en {leave_in_minutes} min"

    local_start = event.start.astimezone(AR_TZ)
    event_time = local_start.strftime("%H:%M")

    msg = (
        f"🚗 *{time_phrase}*\n"
        f"📅 {event.title} a las {event_time}\n"
        f"📍 {event.location}\n"
        f"⏱ Tiempo de viaje: {travel_str} (con tráfico)"
    )
    recipients = [responsible_wa] if responsible_wa else None
    broadcast_whatsapp_message(msg, recipients=recipients)
    logger.info(
        "logistics_alert_fired",
        event=event.title,
        leave_in=leave_in_minutes,
        recipient=responsible_wa or "all",
    )


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
            event_title = row.get("event_title") or "Evento"
            destination = row.get("destination", "")

            event_time_str = ""
            event_start_raw = row.get("event_start_utc")
            if event_start_raw:
                start_dt = datetime.fromisoformat(event_start_raw).astimezone(AR_TZ)
                event_time_str = start_dt.strftime("%H:%M")

            leave_at_str = ""
            leave_at_raw = row.get("leave_at_utc")
            if leave_at_raw:
                leave_dt = datetime.fromisoformat(leave_at_raw).astimezone(AR_TZ)
                leave_at_str = leave_dt.strftime("%H:%M")

            travel_min = row.get("travel_minutes")
            travel_str = (
                f"{travel_min} min" if travel_min and travel_min < 60
                else f"{travel_min // 60}h {travel_min % 60}min" if travel_min
                else None
            )

            # Prefer the responsible person; fall back to all family members
            responsible_wa = row.get("responsible_whatsapp")
            recipients = [responsible_wa] if responsible_wa else (row.get("send_to") or None)

            lines = [f"🚗 *¡Hora de prepararse!*"]
            lines.append(f"📅 {event_title}" + (f" a las {event_time_str}" if event_time_str else ""))
            lines.append(f"📍 {destination}")
            if leave_at_str:
                lines.append(f"🕐 Salís a las *{leave_at_str}*")
            if travel_str:
                lines.append(f"⏱ Tráfico estimado: {travel_str}")
            msg = "\n".join(lines)

            broadcast_whatsapp_message(msg, recipients=recipients)
            _mark_alert_sent(row["calendar_event_id"])
            logger.info(
                "logistics_due_alert_sent",
                event=event_title,
                destination=destination,
                recipient=responsible_wa or "all",
            )
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

    # Logistics: poll calendar every N minutes
    _scheduler.add_job(
        poll_calendar_and_schedule,
        trigger=IntervalTrigger(minutes=s.scheduler_interval_minutes),
        id="logistics_poll",
        name="Logistics: poll calendar & send alerts",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on start
    )

    # Daily morning summary at 7:00 AM Argentina time
    _scheduler.add_job(
        _run_daily_summary,
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Argentina/Buenos_Aires"),
        id="daily_summary",
        name="Daily morning summary at 7am AR",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("scheduler_started", interval_min=s.scheduler_interval_minutes)
    return _scheduler


async def _run_daily_summary() -> None:
    """Wrapper that imports and calls send_daily_summary (avoids circular import at module load)."""
    try:
        from agents.schedule.daily_summary import send_daily_summary
        await send_daily_summary()
    except Exception:
        logger.exception("daily_summary_scheduler_error")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
