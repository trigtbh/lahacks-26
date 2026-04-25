"""
executor.py
Executes workflow steps using OAuth tokens for Google (Gmail + Calendar)
and Slack. Other apps fall back to Zapier webhooks.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

import httpx
import google.oauth2.credentials
import google.auth.transport.requests
from googleapiclient.discovery import build

import token_store
import zapier_store

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


# ─────────────────────────────────────────────
# Param resolver
# ─────────────────────────────────────────────

def _resolve(value: Any) -> Any:
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


# ─────────────────────────────────────────────
# Google credentials helper
# ─────────────────────────────────────────────

async def _get_google_creds(user_id: str) -> google.oauth2.credentials.Credentials:
    doc = await token_store.get_token(user_id, "google")
    if not doc:
        raise ValueError(f"No Google OAuth token for user '{user_id}' — connect via /auth/google")

    creds = google.oauth2.credentials.Credentials(
        token=doc["access_token"],
        refresh_token=doc.get("refresh_token"),
        token_uri=doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=doc.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        await token_store.save_token(user_id, "google", {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": list(creds.scopes or []),
        })

    return creds


# ─────────────────────────────────────────────
# Gmail handlers
# ─────────────────────────────────────────────

async def _gmail_send_email(user_id: str, params: dict) -> None:
    creds = await _get_google_creds(user_id)
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
    creds = await _get_google_creds(user_id)
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


# ─────────────────────────────────────────────
# Google Calendar handlers
# ─────────────────────────────────────────────

async def _gcal_create_event(user_id: str, params: dict) -> None:
    creds = await _get_google_creds(user_id)
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
    creds = await _get_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)

    # Fetch the next upcoming event
    now = datetime.now(timezone.utc).isoformat()
    result = service.events().list(
        calendarId="primary", timeMin=now, maxResults=10,
        singleEvents=True, orderBy="startTime",
    ).execute()

    event = next(
        (e for e in result.get("items", []) if "dateTime" in e.get("start", {})),
        None,
    )
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
    creds = await _get_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc).isoformat()
    result = service.events().list(
        calendarId="primary", timeMin=now, maxResults=10,
        singleEvents=True, orderBy="startTime",
    ).execute()

    event = next(
        (e for e in result.get("items", []) if "dateTime" in e.get("start", {})),
        None,
    )
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
    ("gmail",            "send_email"):   _gmail_send_email,
    ("gmail",            "draft_email"):  _gmail_draft_email,
    ("google_calendar",  "create_event"): _gcal_create_event,
    ("google_calendar",  "push_event"):   _gcal_push_event,
    ("google_calendar",  "cancel_event"): _gcal_cancel_event,
}

_SLACK_ACTIONS = {"send_dm", "send_channel"}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def execute_workflow(user_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    completed: list[dict] = []
    failed:    list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as fallback_client:
        for step in steps:
            app    = step.get("app", "")
            action = step.get("action", "")
            resolved = {k: _resolve(v) for k, v in step.get("params", {}).items()}
            label = f"{app}.{action}"

            try:
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
    }
