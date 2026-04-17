"""Daily morning summary – sent automatically at 7am Argentina time."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import structlog

from agents.schedule.calendar_client import AR_TZ, list_upcoming_events
from core.models import CalendarEvent, FamilyMember
from core.supabase_client import get_supabase
from core.whatsapp import send_whatsapp_message, broadcast_whatsapp_message

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


def _get_due_tasks_today() -> tuple:
    """Fetch tasks and homework due today or overdue."""
    try:
        from core.supabase_client import get_due_tasks_today, get_pending_homework
        tasks = get_due_tasks_today()
        today_str = date.today().isoformat()
        homework = [h for h in get_pending_homework() if h.due_date <= today_str]
        return tasks, homework
    except Exception:
        return [], []


def _detect_child_conflicts(
    events: List[CalendarEvent],
    days_ahead: int = 7,
) -> List[Tuple[str, CalendarEvent, CalendarEvent]]:
    """Return (child_name, event1, event2) tuples where two events overlap for the same child.

    Only looks at events within the next `days_ahead` days from now.
    """
    now_ar = datetime.now(AR_TZ)
    cutoff = now_ar + timedelta(days=days_ahead)

    by_child: dict = defaultdict(list)
    for event in events:
        if event.children and event.start.astimezone(AR_TZ) <= cutoff:
            for child in event.children:
                by_child[child].append(event)

    conflicts: List[Tuple[str, CalendarEvent, CalendarEvent]] = []
    for child, child_events in by_child.items():
        child_events_sorted = sorted(child_events, key=lambda e: e.start)
        for i, e1 in enumerate(child_events_sorted):
            for e2 in child_events_sorted[i + 1:]:
                if e2.start >= e1.end:
                    break  # sorted by start; no further overlaps with e1
                conflicts.append((child, e1, e2))

    return conflicts


def _build_summary_for_member(
    member: FamilyMember,
    today: date,
    today_events: List[CalendarEvent],
    tomorrow_events: List[CalendarEvent],
    due_tasks: list,
    due_homework: list,
    conflicts: List[Tuple[str, CalendarEvent, CalendarEvent]],
) -> str:
    """Build a personalized morning summary showing only events/tasks for this member."""
    nick = member.nickname.lower()

    # Events where this member is responsible, or events with no responsible assigned
    my_today_events = [
        e for e in today_events
        if not e.responsible_nickname
        or e.responsible_nickname.strip().lower() == nick
    ]
    my_tomorrow_events = [
        e for e in tomorrow_events
        if not e.responsible_nickname
        or e.responsible_nickname.strip().lower() == nick
    ]

    # Tasks assigned to this member, or tasks with no assignee
    my_tasks = [
        t for t in due_tasks
        if not t.get("assignee")
        or t.get("assignee", "").strip().lower() == nick
    ]

    day_name = DAYS_ES.get(today.strftime("%A"), today.strftime("%A"))
    month_name = MONTHS_ES.get(today.month, "")
    date_str = f"{day_name} {today.day} de {month_name}"

    lines = [f"📅 *Buenos días, {member.name}!* {date_str}\n"]

    if my_today_events:
        lines.append("*Tu agenda de hoy:*")
        for e in my_today_events:
            local = e.start.astimezone(AR_TZ)
            time_str = local.strftime("%H:%M")
            line = f"• {time_str} – {e.title}"
            if e.location:
                line += f" 📍 {e.location}"
            if e.children:
                line += f" ({', '.join(e.children)})"
            lines.append(line)
    else:
        lines.append("No tenés eventos agendados para hoy. 🎉")

    if my_tasks:
        lines.append("\n*Tus tareas pendientes:*")
        for t in my_tasks:
            lines.append(f"• {t['title']}")

    if due_homework:
        lines.append("\n*Deberes:*")
        for h in due_homework:
            lines.append(f"• {h.child_name}: {h.description} ({h.subject})")

    # Overlap conflicts – show to all adults so the family can coordinate
    if conflicts:
        lines.append("\n⚠️ *Conflictos de horario detectados:*")
        for child, e1, e2 in conflicts:
            t1 = e1.start.astimezone(AR_TZ).strftime("%-d/%-m %H:%M")
            t2 = e2.start.astimezone(AR_TZ).strftime("%-d/%-m %H:%M")
            lines.append(
                f"• *{child}*: _{e1.title}_ ({t1}) se superpone con _{e2.title}_ ({t2})"
            )
        lines.append("👆 Revisá y elegí cuál actividad mantener.")

    if my_tomorrow_events:
        lines.append("\n*Mañana (tu agenda):*")
        for e in my_tomorrow_events:
            local = e.start.astimezone(AR_TZ)
            time_str = local.strftime("%H:%M")
            lines.append(f"• {time_str} – {e.title}")

    return "\n".join(lines)


async def send_daily_summary() -> None:
    """Send a personalized morning summary to each adult family member."""
    from core.supabase_client import get_family_members

    now_ar = datetime.now(AR_TZ)
    today = now_ar.date()

    if _already_sent(today):
        logger.debug("daily_summary_already_sent", date=today.isoformat())
        return

    today_start = now_ar.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tomorrow_end = today_end + timedelta(days=1)

    all_events = list_upcoming_events(days=2)
    today_events = [
        e for e in all_events
        if today_start <= e.start.astimezone(AR_TZ) < today_end
    ]
    tomorrow_events = [
        e for e in all_events
        if today_end <= e.start.astimezone(AR_TZ) < tomorrow_end
    ]

    due_tasks, due_homework = _get_due_tasks_today()

    # Check for child schedule conflicts in the next 7 days
    week_events = list_upcoming_events(days=7)
    conflicts = _detect_child_conflicts(week_events, days_ahead=7)

    try:
        adults = [m for m in get_family_members() if not m.is_minor and m.whatsapp_number]
    except Exception:
        logger.warning("daily_summary_members_fallback")
        adults = []

    sent_content: Optional[str] = None

    if adults:
        for member in adults:
            try:
                content = _build_summary_for_member(
                    member, today, today_events, tomorrow_events,
                    due_tasks, due_homework, conflicts,
                )
                send_whatsapp_message(member.whatsapp_number, content)
                logger.info("daily_summary_sent_to", nickname=member.nickname, date=today.isoformat())
                if sent_content is None:
                    sent_content = content
            except Exception:
                logger.exception("daily_summary_member_error", nickname=member.nickname)
    else:
        # Fallback: broadcast a generic summary if no adults are registered in DB
        try:
            from core.whatsapp import _get_broadcast_recipients
            from core.config import get_settings

            content = _build_generic_summary(today, today_events, tomorrow_events, due_tasks, due_homework, conflicts)
            broadcast_whatsapp_message(content)
            sent_content = content
            logger.info("daily_summary_sent_generic", date=today.isoformat())
        except Exception:
            logger.exception("daily_summary_generic_error", date=today.isoformat())

    if sent_content is not None:
        try:
            _mark_sent(today, sent_content)
        except Exception:
            logger.warning("daily_summary_mark_sent_error", date=today.isoformat())


def _build_generic_summary(
    today: date,
    today_events: List[CalendarEvent],
    tomorrow_events: List[CalendarEvent],
    due_tasks: list,
    due_homework: list,
    conflicts: List[Tuple[str, CalendarEvent, CalendarEvent]],
) -> str:
    """Fallback summary without personalization when no adult members are in DB."""
    day_name = DAYS_ES.get(today.strftime("%A"), today.strftime("%A"))
    month_name = MONTHS_ES.get(today.month, "")
    date_str = f"{day_name} {today.day} de {month_name}"

    lines = [f"📅 *Buenos días!* {date_str}\n"]

    if today_events:
        lines.append("*Agenda de hoy:*")
        for e in today_events:
            local = e.start.astimezone(AR_TZ)
            time_str = local.strftime("%H:%M")
            line = f"• {time_str} – {e.title}"
            if e.location:
                line += f" 📍 {e.location}"
            if e.responsible_nickname:
                line += f" ({e.responsible_nickname})"
            lines.append(line)
    else:
        lines.append("No hay eventos agendados para hoy. 🎉")

    if due_tasks:
        lines.append("\n*Tareas pendientes:*")
        for t in due_tasks:
            assignee = f" → {t['assignee']}" if t.get("assignee") else ""
            lines.append(f"• {t['title']}{assignee}")

    if due_homework:
        lines.append("\n*Deberes:*")
        for h in due_homework:
            lines.append(f"• {h.child_name}: {h.description} ({h.subject})")

    if conflicts:
        lines.append("\n⚠️ *Conflictos de horario:*")
        for child, e1, e2 in conflicts:
            t1 = e1.start.astimezone(AR_TZ).strftime("%-d/%-m %H:%M")
            t2 = e2.start.astimezone(AR_TZ).strftime("%-d/%-m %H:%M")
            lines.append(
                f"• *{child}*: _{e1.title}_ ({t1}) se superpone con _{e2.title}_ ({t2})"
            )
        lines.append("👆 Revisá y elegí cuál actividad mantener.")

    if tomorrow_events:
        lines.append("\n*Mañana:*")
        for e in tomorrow_events:
            local = e.start.astimezone(AR_TZ)
            time_str = local.strftime("%H:%M")
            lines.append(f"• {time_str} – {e.title}")

    return "\n".join(lines)
