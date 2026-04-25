"""
executor.py
Executes workflow steps for Gmail and Google Calendar.

Resolves two dynamic values inline (no external AI layer needed):
  - "calendar.next_event"            -> fetches the user's next timed GCal event
  - "calendar.next_event.attendees"  -> extracts attendee emails from that event
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

from google_client import get_calendar_service, get_gmail_service

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Calendar resolver (inline, no ai/ needed)
# ─────────────────────────────────────────────

def _fetch_next_event() -> dict | None:
    """Return the user's next upcoming timed calendar event, or None."""
    service = get_calendar_service()
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    for event in result.get("items", []):
        if "dateTime" in event.get("start", {}):
            return event
    return None


def _resolve(value: Any, event: dict | None) -> Any:
    """
    Swap resolver strings for real values.
    Only handles the two keys needed by the 'running late' workflow.
    Any other value is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    if value == "calendar.next_event":
        return event
    if value == "calendar.next_event.attendees":
        if not event:
            return []
        return [a["email"] for a in event.get("attendees", []) if "email" in a]
    return value


# ─────────────────────────────────────────────
# Action handlers
# ─────────────────────────────────────────────

def _gmail_send_email(params: dict[str, Any]) -> None:
    service = get_gmail_service()

    to = params["to"]
    if isinstance(to, list):
        to = ", ".join(to)
    if not to:
        raise ValueError("No recipients — 'to' resolved to an empty list")

    msg = MIMEText(params.get("body", ""))
    msg["to"]      = to
    msg["subject"] = params.get("subject", "(no subject)")
    if params.get("cc"):
        msg["cc"] = params["cc"] if isinstance(params["cc"], str) else ", ".join(params["cc"])

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    log.info("Email sent to %s", to)


def _gcal_push_event(params: dict[str, Any]) -> None:
    service = get_calendar_service()
    event = params["event_ref"]
    if not isinstance(event, dict):
        raise ValueError("event_ref must be a full event object (use resolver 'calendar.next_event')")

    by_minutes: int = int(params.get("by_minutes", 15))

    start_dt = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
    end_dt   = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))

    event["start"]["dateTime"] = (start_dt + timedelta(minutes=by_minutes)).isoformat()
    event["end"]["dateTime"]   = (end_dt   + timedelta(minutes=by_minutes)).isoformat()

    service.events().update(
        calendarId="primary",
        eventId=event["id"],
        body=event,
    ).execute()
    log.info("Event '%s' pushed by %d min", event.get("summary", event["id"]), by_minutes)


_ACTION_MAP: dict[tuple[str, str], Any] = {
    ("gmail",           "send_email"):  _gmail_send_email,
    ("google_calendar", "push_event"):  _gcal_push_event,
}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def execute_workflow(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Resolve calendar values and run each step.

    Calendar API is called at most once (lazy, cached in `event`).
    Returns:
        {
          status:          "success" | "partial" | "failed",
          steps_completed: [...],
          steps_failed:    [...],
          event_title:     str | None,   -- the meeting that was affected
        }
    """
    event: dict | None = None
    event_fetched = False

    completed: list[dict] = []
    failed:    list[dict] = []

    for step in steps:
        app    = step.get("app", "")
        action = step.get("action", "")
        raw_params: dict = dict(step.get("params", {}))

        handler = _ACTION_MAP.get((app, action))
        if not handler:
            failed.append({"step": f"{app}.{action}", "error": "No handler registered"})
            continue

        # Resolve dynamic params — fetch event only when first needed
        resolved_params: dict[str, Any] = {}
        needs_event = any(
            isinstance(v, str) and v.startswith("calendar.next_event")
            for v in raw_params.values()
        )
        if needs_event and not event_fetched:
            event = _fetch_next_event()
            event_fetched = True

        for k, v in raw_params.items():
            resolved_params[k] = _resolve(v, event)

        try:
            handler(resolved_params)
            completed.append({"step": f"{app}.{action}", "params": {
                k: ("<event object>" if isinstance(v, dict) else v)
                for k, v in resolved_params.items()
            }})
        except Exception as exc:
            log.error("Step %s.%s failed: %s", app, action, exc, exc_info=True)
            failed.append({"step": f"{app}.{action}", "error": str(exc)})

    status = "success" if not failed else ("failed" if not completed else "partial")
    return {
        "status":          status,
        "steps_completed": completed,
        "steps_failed":    failed,
        "event_title":     event.get("summary") if event else None,
    }
