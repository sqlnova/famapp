"""Google Calendar client using service account credentials."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import pytz
import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.config import get_settings
from core.models import CalendarEvent

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
AR_TZ = pytz.timezone("America/Argentina/Buenos_Aires")


def _get_service():
    s = get_settings()
    creds_path = s.resolve_google_credentials_path()
    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _to_utc_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


_RESPONSIBLE_TAG_RE = re.compile(r"\[responsable:([^\]]+)\]", re.IGNORECASE)
_CHILDREN_TAG_RE = re.compile(r"\[hijos:([^\]]+)\]", re.IGNORECASE)


def _extract_metadata(description: Optional[str]) -> tuple[Optional[str], Optional[str], List[str]]:
    """Return (clean_description, responsible_nickname, children) after stripping tags."""
    if not description:
        return description, None, []

    working = description
    responsible = None
    children: List[str] = []

    responsible_match = _RESPONSIBLE_TAG_RE.search(working)
    if responsible_match:
        responsible = responsible_match.group(1).strip()
        working = _RESPONSIBLE_TAG_RE.sub("", working)

    children_match = _CHILDREN_TAG_RE.search(working)
    if children_match:
        children = [c.strip() for c in children_match.group(1).split(",") if c.strip()]
        working = _CHILDREN_TAG_RE.sub("", working)

    clean = working.strip() or None
    return clean, responsible, children


def _parse_event(raw: dict) -> CalendarEvent:
    """Parse a raw Google Calendar API event dict into a CalendarEvent."""
    start_raw = raw.get("start", {})
    end_raw = raw.get("end", {})

    def parse_dt(d: dict) -> datetime:
        if "dateTime" in d:
            return datetime.fromisoformat(d["dateTime"])
        # All-day event
        return datetime.fromisoformat(d["date"] + "T00:00:00+00:00")

    raw_desc = raw.get("description")
    clean_desc, responsible, children = _extract_metadata(raw_desc)
    # Recurring event instances have recurringEventId — disable auto-alerts to
    # avoid daily spam for habitual events (school runs, weekly classes, etc.).
    is_recurring_instance = "recurringEventId" in raw

    return CalendarEvent(
        id=raw.get("id"),
        recurring_event_id=raw.get("recurringEventId"),
        title=raw.get("summary", "(sin título)"),
        start=parse_dt(start_raw),
        end=parse_dt(end_raw),
        location=raw.get("location"),
        description=clean_desc,
        attendees=[
            a["email"] for a in raw.get("attendees", []) if not a.get("self")
        ],
        responsible_nickname=responsible,
        children=children,
        recurrence=raw.get("recurrence", []) or [],
        alerts_enabled=not is_recurring_instance,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def list_upcoming_events(
    days: int = 7,
    max_results: int = 20,
) -> List[CalendarEvent]:
    """Return upcoming events for the next `days` days."""
    s = get_settings()
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days)

    try:
        result = (
            service.events()
            .list(
                calendarId=s.google_calendar_id,
                timeMin=_to_utc_rfc3339(now),
                timeMax=_to_utc_rfc3339(time_max),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = [_parse_event(e) for e in result.get("items", [])]
        logger.info("calendar_events_fetched", count=len(events), days=days)
        return events
    except HttpError as e:
        logger.error("calendar_list_error", error=str(e))
        raise


def get_events_in_window(
    hours_ahead: int = 3,
) -> List[CalendarEvent]:
    """Return events starting in the next `hours_ahead` hours that have a location."""
    s = get_settings()
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(hours=hours_ahead)

    try:
        result = (
            service.events()
            .list(
                calendarId=s.google_calendar_id,
                timeMin=_to_utc_rfc3339(now),
                timeMax=_to_utc_rfc3339(time_max),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = [
            _parse_event(e)
            for e in result.get("items", [])
            if e.get("location")  # only events with a location
        ]
        logger.info("calendar_window_events", count=len(events), hours=hours_ahead)
        return events
    except HttpError as e:
        logger.error("calendar_window_error", error=str(e))
        raise


def create_event(
    event: CalendarEvent,
    recurrence: Optional[List[str]] = None,
) -> CalendarEvent:
    """Create a new calendar event. Returns the created event with its ID.

    Args:
        event: The event to create.
        recurrence: Optional RFC 5545 recurrence rules, e.g.
                    ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20241130T235959Z"]
    """
    s = get_settings()
    service = _get_service()

    body: dict = {
        "summary": event.title,
        "start": {"dateTime": _to_utc_rfc3339(event.start), "timeZone": "America/Argentina/Buenos_Aires"},
        "end":   {"dateTime": _to_utc_rfc3339(event.end),   "timeZone": "America/Argentina/Buenos_Aires"},
    }
    if event.location:
        body["location"] = event.location
    # Build description: user text + optional [responsable:nick] tag
    desc_parts = [event.description] if event.description else []
    if event.responsible_nickname:
        desc_parts.append(f"[responsable:{event.responsible_nickname}]")
    if event.children:
        desc_parts.append(f"[hijos:{','.join(event.children)}]")
    if desc_parts:
        body["description"] = "\n".join(desc_parts)
    if event.attendees:
        body["attendees"] = [{"email": a} for a in event.attendees]
    if recurrence:
        body["recurrence"] = recurrence

    try:
        created = service.events().insert(calendarId=s.google_calendar_id, body=body).execute()
        logger.info("calendar_event_created", title=event.title, id=created.get("id"), recurring=bool(recurrence))
        return _parse_event(created)
    except HttpError as e:
        logger.error("calendar_create_error", error=str(e))
        raise


def update_event(event_id: str, updates: dict[str, Any]) -> CalendarEvent:
    """Update an existing event and return the updated object."""
    s = get_settings()
    service = _get_service()

    try:
        current = service.events().get(calendarId=s.google_calendar_id, eventId=event_id).execute()
        body = dict(current)

        if "title" in updates and updates["title"] is not None:
            body["summary"] = updates["title"]
        if "start" in updates and updates["start"] is not None:
            body["start"] = {
                "dateTime": _to_utc_rfc3339(updates["start"]),
                "timeZone": "America/Argentina/Buenos_Aires",
            }
        if "end" in updates and updates["end"] is not None:
            body["end"] = {
                "dateTime": _to_utc_rfc3339(updates["end"]),
                "timeZone": "America/Argentina/Buenos_Aires",
            }
        if "location" in updates:
            body["location"] = updates["location"] or None

        # Merge [responsable:nick] tag preserving existing free text.
        existing_desc, existing_responsible, existing_children = _extract_metadata(current.get("description"))
        responsible = updates.get("responsible_nickname", existing_responsible)
        children = updates.get("children", existing_children)
        desc_parts = [existing_desc] if existing_desc else []
        if responsible:
            desc_parts.append(f"[responsable:{responsible}]")
        if children:
            desc_parts.append(f"[hijos:{','.join(children)}]")
        if desc_parts:
            body["description"] = "\n".join(desc_parts)
        else:
            body.pop("description", None)

        updated = service.events().update(
            calendarId=s.google_calendar_id,
            eventId=event_id,
            body=body,
        ).execute()
        logger.info("calendar_event_updated", id=event_id)
        return _parse_event(updated)
    except HttpError as e:
        logger.error("calendar_update_error", id=event_id, error=str(e))
        raise


def delete_event(event_id: str) -> None:
    """Delete an event by id."""
    s = get_settings()
    service = _get_service()
    try:
        service.events().delete(calendarId=s.google_calendar_id, eventId=event_id).execute()
        logger.info("calendar_event_deleted", id=event_id)
    except HttpError as e:
        logger.error("calendar_delete_error", id=event_id, error=str(e))
        raise


def list_recurring_series(
    days: int = 365,
    max_results: int = 250,
) -> List[CalendarEvent]:
    """Return recurring series masters (not individual instances)."""
    s = get_settings()
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days)
    try:
        result = (
            service.events()
            .list(
                calendarId=s.google_calendar_id,
                timeMin=_to_utc_rfc3339(now),
                timeMax=_to_utc_rfc3339(time_max),
                maxResults=max_results,
                singleEvents=False,
            )
            .execute()
        )
        items = [
            e for e in result.get("items", [])
            if e.get("recurrence") and not e.get("recurringEventId")
        ]
        return [_parse_event(e) for e in items]
    except HttpError as e:
        logger.error("calendar_recurring_list_error", error=str(e))
        raise


def format_events_for_whatsapp(events: List[CalendarEvent]) -> str:
    """Format a list of events into a readable WhatsApp message."""
    if not events:
        return "No tenés eventos próximos en el calendario."

    lines = []
    for e in events:
        local_start = e.start.astimezone(AR_TZ)
        date_str = local_start.strftime("%-d/%-m")
        time_str = local_start.strftime("%H:%M")
        line = f"• *{e.title}* – {date_str} a las {time_str}"
        if e.location:
            line += f"\n  📍 {e.location}"
        lines.append(line)

    return "📅 Próximos eventos:\n\n" + "\n\n".join(lines)
