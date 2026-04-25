"""
executor.py
Executes workflow steps using OAuth tokens for Google (Gmail + Calendar)
and Slack. Other apps fall back to Zapier webhooks.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

import httpx
from googleapiclient.discovery import build

import token_store
import zapier_store
import google_people
from google_auth import get_google_creds

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


# ─────────────────────────────────────────────
# Param resolvers
# ─────────────────────────────────────────────

def _resolve_static(value: Any) -> Any:
    """Resolve time-based resolver keys synchronously."""
    if not isinstance(value, str):
        return value
    if value == "time.now":
        return datetime.now(timezone.utc).isoformat()
    if value.startswith("time.now+") and value.endswith("m"):
        try:
            minutes = int(value[len("time.now+"):-1])
            return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        except ValueError:
            pass
    return value


async def _resolve_params(user_id: str, params: dict) -> dict:
    """Resolve all params for a step, including API-backed contact/calendar resolvers."""
    resolved = {}
    for key, value in params.items():
        value = _resolve_static(value)

        if isinstance(value, str):
            if value.startswith("user.contacts.email:"):
                name = value[len("user.contacts.email:"):]
                value = await google_people.resolve_contact_email(user_id, name)

            elif value.startswith("user.contacts.by_name:"):
                name = value[len("user.contacts.by_name:"):]
                matches = await google_people.search_contacts(user_id, name)
                value = matches[0] if matches else {}

            elif value in _CALENDAR_NEXT_EVENT_RESOLVERS:
                value = await _resolve_calendar_next_event(user_id, value)

        resolved[key] = value
    return resolved


_CALENDAR_NEXT_EVENT_RESOLVERS = {
    "calendar.next_event",
    "calendar.next_event.title",
    "calendar.next_event.attendees",
    "calendar.next_event.start_time",
    "calendar.next_event.location",
}


async def _resolve_calendar_next_event(user_id: str, resolver_key: str) -> Any:
    creds = await get_google_creds(user_id)
    event = await _get_next_event(creds)
    if not event:
        raise ValueError("No upcoming calendar event found")
    if resolver_key == "calendar.next_event":
        return event
    if resolver_key == "calendar.next_event.title":
        return event.get("summary", "")
    if resolver_key == "calendar.next_event.attendees":
        return [a["email"] for a in event.get("attendees", [])]
    if resolver_key == "calendar.next_event.start_time":
        return event.get("start", {}).get("dateTime", "")
    if resolver_key == "calendar.next_event.location":
        return event.get("location", "")
    return event


# ─────────────────────────────────────────────
# Shared calendar helper
# ─────────────────────────────────────────────

async def _get_next_event(creds) -> dict | None:
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc).isoformat()
    result = service.events().list(
        calendarId="primary", timeMin=now, maxResults=10,
        singleEvents=True, orderBy="startTime",
    ).execute()
    return next(
        (e for e in result.get("items", []) if "dateTime" in e.get("start", {})),
        None,
    )


# ─────────────────────────────────────────────
# Gmail handlers
# ─────────────────────────────────────────────

async def _gmail_send_email(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    service = build("gmail", "v1", credentials=creds)

    to = params["to"]
    if isinstance(to, list):
        to = ", ".join(to)
    if not to:
        raise ValueError("No recipient — 'to' is empty")

    msg = MIMEText(params.get("body", ""))
    msg["to"] = to
    msg["subject"] = params.get("subject", "(no subject)")
    if params.get("cc"):
        msg["cc"] = params["cc"] if isinstance(params["cc"], str) else ", ".join(params["cc"])

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    log.info("Gmail sent to %s", to)


async def _gmail_draft_email(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    service = build("gmail", "v1", credentials=creds)

    to = params["to"]
    if isinstance(to, list):
        to = ", ".join(to)

    msg = MIMEText(params.get("body", ""))
    msg["to"] = to
    msg["subject"] = params.get("subject", "(no subject)")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    log.info("Gmail draft created for %s", to)


async def _gmail_search_email(user_id: str, params: dict) -> list[dict]:
    creds = await get_google_creds(user_id)
    service = build("gmail", "v1", credentials=creds)

    max_results = int(params.get("max_results", 5))
    result = service.users().messages().list(
        userId="me",
        q=params["query"],
        maxResults=max_results,
    ).execute()

    messages = result.get("messages", [])
    log.info("Gmail search %r → %d result(s)", params["query"], len(messages))
    return messages


# ─────────────────────────────────────────────
# Google Calendar handlers
# ─────────────────────────────────────────────

async def _gcal_create_event(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)

    event: dict = {
        "summary": params.get("title", ""),
        "start": {"dateTime": params["start_time"], "timeZone": "UTC"},
        "end":   {"dateTime": params["end_time"],   "timeZone": "UTC"},
    }
    if params.get("attendees"):
        attendees = params["attendees"]
        if isinstance(attendees, str):
            attendees = [a.strip() for a in attendees.split(",")]
        event["attendees"] = [{"email": a} for a in attendees]
    if params.get("location"):
        event["location"] = params["location"]
    if params.get("description"):
        event["description"] = params["description"]

    service.events().insert(calendarId="primary", body=event).execute()
    log.info("GCal event created: %s", params.get("title"))


async def _gcal_push_event(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)

    event = await _get_next_event(creds)
    if not event:
        raise ValueError("No upcoming timed event found")

    by_minutes = int(params.get("by_minutes", 15))
    start_dt = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
    end_dt   = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))
    event["start"]["dateTime"] = (start_dt + timedelta(minutes=by_minutes)).isoformat()
    event["end"]["dateTime"]   = (end_dt   + timedelta(minutes=by_minutes)).isoformat()

    service.events().update(calendarId="primary", eventId=event["id"], body=event).execute()
    log.info("GCal event '%s' pushed by %d min", event.get("summary"), by_minutes)


async def _gcal_cancel_event(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)

    event = await _get_next_event(creds)
    if not event:
        raise ValueError("No upcoming timed event found to cancel")

    service.events().delete(calendarId="primary", eventId=event["id"]).execute()
    log.info("GCal event '%s' cancelled", event.get("summary"))


# ─────────────────────────────────────────────
# Slack handlers
# ─────────────────────────────────────────────

async def _slack_send(user_id: str, params: dict, action: str) -> None:
    doc = await token_store.get_token(user_id, "slack")
    if not doc:
        raise ValueError(f"No Slack OAuth token for user '{user_id}' — connect via /auth/slack")

    channel = params.get("channel") if action == "send_channel" else params.get("to")
    payload = {
        "channel": channel,
        "text": params.get("message", ""),
        "as_user": True,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {doc['access_token']}"},
            json=payload,
        )
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"Slack API error: {data.get('error')}")
    log.info("Slack message sent to %s", channel)


# ─────────────────────────────────────────────
# Action router
# ─────────────────────────────────────────────

_OAUTH_HANDLERS: dict[tuple[str, str], Any] = {
    ("gmail",            "send_email"):    _gmail_send_email,
    ("gmail",            "draft_email"):   _gmail_draft_email,
    ("gmail",            "search_email"):  _gmail_search_email,
    ("google_calendar",  "create_event"):  _gcal_create_event,
    ("google_calendar",  "push_event"):    _gcal_push_event,
    ("google_calendar",  "cancel_event"):  _gcal_cancel_event,
}

_SLACK_ACTIONS = {"send_dm", "send_channel"}


async def _ensure_app_connection(user_id: str, app: str) -> None:
    if app in {"gmail", "google_calendar"}:
        doc = await token_store.get_token(user_id, "google")
        if not doc:
            raise ValueError(f"Google account not connected for user '{user_id}'")
    elif app == "slack":
        doc = await token_store.get_token(user_id, "slack")
        if not doc:
            raise ValueError(f"Slack account not connected for user '{user_id}'")


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def _summarize_step_preview(app: str, action: str, resolved: dict[str, Any]) -> str:
    if app == "google_calendar" and action == "push_event":
        return f"Push the next calendar event by {resolved.get('by_minutes', '?')} minutes"
    if app == "google_calendar" and action == "create_event":
        return f"Create calendar event '{resolved.get('title', 'Untitled')}'"
    if app == "google_calendar" and action == "cancel_event":
        return "Cancel the next calendar event"
    if app == "gmail" and action == "send_email":
        to = resolved.get("to", "")
        recipient_count = len(to) if isinstance(to, list) else (1 if to else 0)
        return f"Send an email to {recipient_count} recipient{'s' if recipient_count != 1 else ''}"
    if app == "gmail" and action == "draft_email":
        return "Create an email draft"
    if app == "slack" and action == "send_dm":
        return f"Send a Slack DM to {resolved.get('to', 'someone')}"
    if app == "slack" and action == "send_channel":
        return f"Post in Slack channel {resolved.get('channel', '')}".strip()
    return f"Run {app}.{action}"


async def preview_workflow(user_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    preview_steps: list[dict[str, Any]] = []
    failed_steps: list[dict[str, Any]] = []

    for step in steps:
        app = step.get("app", "")
        action = step.get("action", "")
        label = f"{app}.{action}"
        try:
            await _ensure_app_connection(user_id, app)
            resolved = await _resolve_params(user_id, step.get("params", {}))
            preview_steps.append({
                "step": label,
                "params": resolved,
                "summary": _summarize_step_preview(app, action, resolved),
                "status": "ready",
            })
        except Exception as exc:
            failed_steps.append({
                "step": label,
                "error": str(exc),
                "status": "error",
            })

    status = "ready" if not failed_steps else ("blocked" if not preview_steps else "partial")
    return {
        "status": status,
        "steps": preview_steps,
        "step_errors": failed_steps,
    }


def workflow_failure_message(result: dict[str, Any]) -> str:
    failed_steps = result.get("steps_failed", [])
    if not failed_steps:
        return "workflow executed"

    failed_errors = [str(step.get("error", "")) for step in failed_steps]
    if any("Google account not connected" in error or "No Google OAuth token" in error for error in failed_errors):
        return "google account not connected"
    if any("Slack account not connected" in error or "No Slack OAuth token" in error for error in failed_errors):
        return "slack account not connected"

    failed_labels = [str(step.get("step", "")) for step in failed_steps]
    if any(label.startswith("gmail.") for label in failed_labels):
        return "gmail action failed"
    if any(label.startswith("google_calendar.") for label in failed_labels):
        return "calendar action failed"
    if any(label.startswith("slack.") for label in failed_labels):
        return "slack action failed"
    return "workflow failed"


async def execute_workflow_stream(user_id: str, steps: list[dict[str, Any]]):
    """Async generator that yields SSE-ready dicts for each step as it runs."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as fallback_client:
        for i, step in enumerate(steps):
            app    = step.get("app", "")
            action = step.get("action", "")
            label  = f"{app}.{action}"
            resolved: dict = {}

            yield {"type": "step_start", "index": i, "label": label}

            try:
                await _ensure_app_connection(user_id, app)
                resolved = await _resolve_params(user_id, step.get("params", {}))

                handler = _OAUTH_HANDLERS.get((app, action))
                if handler:
                    await handler(user_id, resolved)
                elif app == "slack" and action in _SLACK_ACTIONS:
                    await _slack_send(user_id, resolved, action)
                else:
                    webhook_url = await zapier_store.get_webhook_url(user_id, app, action)
                    if not webhook_url:
                        raise ValueError(f"No handler or Zapier webhook configured for {label}")
                    resp = await fallback_client.post(webhook_url, json=resolved)
                    resp.raise_for_status()
                    log.info("Zapier webhook fired for %s → HTTP %s", label, resp.status_code)

                yield {"type": "step_done", "index": i, "params": resolved}

            except Exception as exc:
                log.error("%s failed: %s", label, exc, exc_info=True)
                yield {"type": "step_error", "index": i, "error": str(exc)}

    yield {"type": "done"}


async def execute_workflow(user_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    completed: list[dict] = []
    failed:    list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as fallback_client:
        for step in steps:
            app    = step.get("app", "")
            action = step.get("action", "")
            label  = f"{app}.{action}"
            resolved: dict = {}

            try:
                await _ensure_app_connection(user_id, app)
                resolved = await _resolve_params(user_id, step.get("params", {}))

                # OAuth path — Google
                handler = _OAUTH_HANDLERS.get((app, action))
                if handler:
                    await handler(user_id, resolved)
                    completed.append({"step": label, "params": resolved})
                    continue

                # OAuth path — Slack
                if app == "slack" and action in _SLACK_ACTIONS:
                    await _slack_send(user_id, resolved, action)
                    completed.append({"step": label, "params": resolved})
                    continue

                # Fallback — Zapier webhook
                webhook_url = await zapier_store.get_webhook_url(user_id, app, action)
                if not webhook_url:
                    raise ValueError(f"No handler or Zapier webhook configured for {label}")

                resp = await fallback_client.post(webhook_url, json=resolved)
                resp.raise_for_status()
                completed.append({"step": label, "params": resolved})
                log.info("Zapier webhook fired for %s → HTTP %s", label, resp.status_code)

            except Exception as exc:
                log.error("%s failed: %s", label, exc, exc_info=True)
                failed.append({"step": label, "error": str(exc)})

    status = "success" if not failed else ("failed" if not completed else "partial")
    return {
        "status":          status,
        "steps_completed": completed,
        "steps_failed":    failed,
        "message":         workflow_failure_message({"steps_failed": failed}),
    }
