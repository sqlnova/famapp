"""Daily morning summary – sent automatically at 7am Argentina time."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import structlog

from agents.schedule.calendar_client import AR_TZ, list_upcoming_events
from core.supabase_client import get_supabase
from core.whatsapp import broadcast_whatsapp_message

logger = structlog.get_logger(__name__)

DAYS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _already_sent(summary_date: date) -> bool:
    client = get_supabase()
    result = (
        client.table("daily_summaries")
        .select("id")
        .eq("summary_date", summary_date.isoformat())
        .execute()
    )
    return len(result.data) > 0


def _mark_sent(summary_date: date, content: str) -> None:
    client = get_supabase()
    client.table("daily_summaries").insert({
        "summary_date": summary_date.isoformat(),
        "content": content,
    }).execute()


def _build_summary_text(today: date) -> str:
    """Fetch today's events and build the WhatsApp summary message."""
    # Fetch events for today only (next 24h starting from midnight)
    events = list_upcoming_events(days=1)

    now_ar = datetime.now(AR_TZ)
    today_start = now_ar.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    today_events = [
        e for e in events
        if today_start <= e.start.astimezone(AR_TZ) < today_end
    ]

    day_name = DAYS_ES.get(today.strftime("%A"), today.strftime("%A"))
    month_name = MONTHS_ES.get(today.month, "")
    date_str = f"{day_name} {today.day} de {month_name}"

    if not today_events:
        return (
            f"📅 *Buenos días!* {date_str}\n\n"
            f"No tenés eventos agendados para hoy. 🎉"
        )

    lines = [f"📅 *Buenos días!* {date_str}\n"]
    lines.append("*Agenda de hoy:*")

    for e in today_events:
        local = e.start.astimezone(AR_TZ)
        time_str = local.strftime("%H:%M")
        line = f"• {time_str} – {e.title}"
        if e.location:
            line += f" 📍 {e.location}"
        lines.append(line)

    # Also include tomorrow's events as a preview
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + timedelta(days=1)
    all_events = list_upcoming_events(days=2)
    tomorrow_events = [
        e for e in all_events
        if tomorrow_start <= e.start.astimezone(AR_TZ) < tomorrow_end
    ]

    if tomorrow_events:
        lines.append("\n*Mañana:*")
        for e in tomorrow_events:
            local = e.start.astimezone(AR_TZ)
            time_str = local.strftime("%H:%M")
            lines.append(f"• {time_str} – {e.title}")

    return "\n".join(lines)


async def send_daily_summary() -> None:
    """Send morning summary if not already sent today."""
    now_ar = datetime.now(AR_TZ)
    today = now_ar.date()

    if _already_sent(today):
        logger.debug("daily_summary_already_sent", date=today.isoformat())
        return

    try:
        content = _build_summary_text(today)
        broadcast_whatsapp_message(content)
        _mark_sent(today, content)
        logger.info("daily_summary_sent", date=today.isoformat())
    except Exception:
        logger.exception("daily_summary_error", date=today.isoformat())
