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
from googleapiclient.discovery import build

import token_store
import zapier_store
import google_people
from google_auth import get_google_creds
from innate_executor import execute_innate, _HANDLERS as _INNATE_HANDLERS
from ai.condition_eval import evaluate_condition
from ai.environment import ALLOWED_ACTIONS

_DOMINOS_SERVICE_URL = os.environ.get("DOMINOS_SERVICE_URL", "http://localhost:3001")

log = logging.getLogger(__name__)

_TIMEOUT = 10.0

# Set of valid innate action names for fast membership checks.
_INNATE_ACTION_NAMES: frozenset[str] = frozenset(_INNATE_HANDLERS.keys())

# Map action name → correct app for common Gemma misroutings (e.g. innate.create_document).
_INNATE_REMAP: dict[str, str] = {
    action: app
    for app, actions in ALLOWED_ACTIONS.items()
    for action in actions
}


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


def _resolve_context_path(path: str, context: dict) -> Any:
    """Walk a dotted path into the context dict. Returns None if any segment is missing."""
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, (list, tuple)):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return node


async def _resolve_params(user_id: str, params: dict, context: dict | None = None) -> dict:
    """Resolve all params for a step, including context refs and API-backed resolvers."""
    if context is None:
        context = {}
    resolved = {}
    for key, value in params.items():
        # Context references take priority.
        if isinstance(value, str) and value.startswith("context."):
            resolved[key] = _resolve_context_path(value[len("context."):], context)
            continue

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

            elif value == "google_maps.directions_to_next_event":
                creds = await get_google_creds(user_id)
                event = await _get_next_event(creds)
                value = event.get("location", "") if event else ""

            elif value.startswith("google_drive.file_by_name:"):
                name = value[len("google_drive.file_by_name:"):]
                value = await _drive_find_file_id(user_id, name)

            elif value == "google_drive.latest_file":
                creds = await get_google_creds(user_id)
                svc = build("drive", "v3", credentials=creds)
                res = svc.files().list(
                    orderBy="modifiedTime desc", pageSize=1,
                    fields="files(id, name)",
                ).execute()
                files = res.get("files", [])
                value = files[0]["id"] if files else ""

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
# Domino's handlers
# ─────────────────────────────────────────────

_DOMINOS_SIZE_CODES = {
    "small": "10SCREEN", "10": "10SCREEN",
    "medium": "12SCREEN", "12": "12SCREEN",
    "large": "14SCREEN", "14": "14SCREEN",
    "xlarge": "16SCREEN", "extra large": "16SCREEN", "16": "16SCREEN",
}

_DOMINOS_TOPPING_CODES = {
    "pepperoni": "P", "sausage": "S", "bacon": "B", "beef": "Du",
    "mushrooms": "M", "onions": "O", "green peppers": "G", "peppers": "Rp",
    "extra cheese": "C",
}


def _build_dominos_item(params: dict) -> dict:
    """Translate classifier size/toppings params into a dominos item dict."""
    size = str(params.get("size", "large")).lower()
    code = _DOMINOS_SIZE_CODES.get(size, "14SCREEN")

    toppings = params.get("toppings", [])
    if isinstance(toppings, str):
        toppings = [toppings]

    options: dict = {"X": {"1/1": "1"}, "C": {"1/1": "1"}}  # default: sauce + cheese
    for topping in toppings:
        tc = _DOMINOS_TOPPING_CODES.get(topping.lower())
        if tc:
            options[tc] = {"1/1": "1"}

    return {"code": code, "options": options}


async def _dominos_order_pizza(user_id: str, params: dict) -> dict:
    creds = await token_store.get_token(user_id, "dominos")
    if not creds:
        raise ValueError(f"No Domino's credentials for user '{user_id}' — connect via onboarding")

    items = params.get("items") or [_build_dominos_item(params)]

    payload = {
        "address":   params.get("address")   or creds.get("address", ""),
        "firstName": params.get("firstName") or creds.get("firstName", "Customer"),
        "lastName":  params.get("lastName")  or creds.get("lastName", ""),
        "phone":     params.get("phone")     or creds.get("phone", "555-555-5555"),
        "email":     creds.get("email", ""),
        "items":     items,
    }
    if not payload["address"]:
        raise ValueError("No delivery address — set one in Domino's credentials")

    if params.get("payment"):
        payload["payment"] = params["payment"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_DOMINOS_SERVICE_URL}/order", json=payload)
        resp.raise_for_status()

    result = resp.json()
    log.info("Dominos order user=%s store=%s price=%s placed=%s",
             user_id, result.get("storeID"), result.get("price"), result.get("placed"))
    return result


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
# Google Maps handlers
# ─────────────────────────────────────────────

async def _maps_get_directions(user_id: str, params: dict) -> dict:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY not configured")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params={
                "origin":      params.get("origin", "current location"),
                "destination": params["destination"],
                "mode":        params.get("mode", "driving"),
                "key":         api_key,
            },
        )
    data = resp.json()
    if data.get("status") != "OK":
        raise ValueError(f"Directions API: {data.get('status')} — {data.get('error_message', '')}")
    leg = data["routes"][0]["legs"][0]
    log.info("Maps directions %r → %r", params.get("origin"), params["destination"])
    return {
        "distance": leg["distance"]["text"],
        "duration": leg["duration"]["text"],
        "summary":  data["routes"][0].get("summary", ""),
    }


async def _maps_search_nearby(user_id: str, params: dict) -> list:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY not configured")
    req: dict = {"query": params["query"], "key": api_key}
    if params.get("location"):
        req["location"] = params["location"]
        req["radius"]   = str(params.get("radius", 1000))
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params=req,
        )
    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise ValueError(f"Places API: {data.get('status')} — {data.get('error_message', '')}")
    results = data.get("results", [])[:5]
    log.info("Maps nearby %r → %d results", params["query"], len(results))
    return [
        {"name": r["name"], "address": r.get("formatted_address", ""), "rating": r.get("rating")}
        for r in results
    ]


# ─────────────────────────────────────────────
# Google Drive handlers
# ─────────────────────────────────────────────

async def _drive_find_file_id(user_id: str, name: str) -> str:
    creds = await get_google_creds(user_id)
    svc = build("drive", "v3", credentials=creds)
    res = svc.files().list(
        q=f"name = '{name}' and trashed = false",
        pageSize=1, fields="files(id, name)",
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else ""


async def _drive_create_document(user_id: str, params: dict) -> dict:
    creds = await get_google_creds(user_id)
    docs_svc = build("docs", "v1", credentials=creds)
    doc = docs_svc.documents().create(body={"title": params["title"]}).execute()
    doc_id = doc["documentId"]
    content = params.get("content", "")
    if content:
        docs_svc.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
    log.info("Drive doc created: %s", doc_id)
    return {"document_id": doc_id, "url": f"https://docs.google.com/document/d/{doc_id}"}


async def _drive_search_files(user_id: str, params: dict) -> list:
    creds = await get_google_creds(user_id)
    svc = build("drive", "v3", credentials=creds)
    max_results = int(params.get("max_results", 5))
    query = params["query"].replace("'", "\\'")
    res = svc.files().list(
        q=f"name contains '{query}' and trashed = false",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
    ).execute()
    files = res.get("files", [])
    log.info("Drive search %r → %d results", params["query"], len(files))
    return files


async def _drive_share_file(user_id: str, params: dict) -> None:
    creds = await get_google_creds(user_id)
    svc = build("drive", "v3", credentials=creds)
    file_id = await _drive_find_file_id(user_id, params["file_name"])
    if not file_id:
        raise ValueError(f"No Drive file found named '{params['file_name']}'")
    role = params.get("role", "reader")
    svc.permissions().create(
        fileId=file_id,
        sendNotificationEmail=True,
        body={"type": "user", "role": role, "emailAddress": params["email"]},
    ).execute()
    log.info("Drive '%s' shared with %s as %s", params["file_name"], params["email"], role)


# ─────────────────────────────────────────────
# Google Flights handler
# ─────────────────────────────────────────────

_CABIN_CLASS_MAP = {"economy": "1", "premium_economy": "2", "business": "3", "first": "4"}


async def _flights_search_flights(user_id: str, params: dict) -> dict:
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    origin      = params["origin"]
    destination = params["destination"]
    if not serpapi_key:
        raise ValueError("SERPAPI_KEY not configured")
    req: dict = {
        "engine":       "google_flights",
        "departure_id": origin,
        "arrival_id":   destination,
        "api_key":      serpapi_key,
    }
    if params.get("departure_date"):
        req["outbound_date"] = params["departure_date"]
    if params.get("return_date"):
        req["return_date"] = params["return_date"]
    if params.get("num_adults"):
        req["adults"] = str(params["num_adults"])
    if params.get("cabin_class"):
        req["travel_class"] = _CABIN_CLASS_MAP.get(params["cabin_class"], "1")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get("https://serpapi.com/search", params=req)
    data = resp.json()
    if "error" in data:
        raise ValueError(f"SerpAPI: {data['error']}")
    best = (data.get("best_flights") or data.get("other_flights") or [])[:5]
    log.info("Flights %s→%s → %d options", origin, destination, len(best))
    return {
        "origin":      origin,
        "destination": destination,
        "flights": [
            {
                "price":    f.get("price"),
                "duration": f.get("total_duration"),
                "stops":    len(f.get("layovers", [])),
                "airline":  (f.get("flights") or [{}])[0].get("airline", ""),
            }
            for f in best
        ],
    }


# ─────────────────────────────────────────────
# Action router
# ─────────────────────────────────────────────

_OAUTH_HANDLERS: dict[tuple[str, str], Any] = {
    ("gmail",            "send_email"):      _gmail_send_email,
    ("gmail",            "draft_email"):     _gmail_draft_email,
    ("gmail",            "search_email"):    _gmail_search_email,
    ("google_calendar",  "create_event"):    _gcal_create_event,
    ("google_calendar",  "push_event"):      _gcal_push_event,
    ("google_calendar",  "cancel_event"):    _gcal_cancel_event,
    ("google_maps",      "get_directions"):  _maps_get_directions,
    ("google_maps",      "search_nearby"):   _maps_search_nearby,
    ("google_drive",     "create_document"): _drive_create_document,
    ("google_drive",     "search_files"):    _drive_search_files,
    ("google_drive",     "share_file"):      _drive_share_file,
    ("google_flights",   "search_flights"):  _flights_search_flights,
    ("dominos",          "order_pizza"):     _dominos_order_pizza,
}

_SLACK_ACTIONS = {"send_dm", "send_channel"}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Core recursive execution engine
# ─────────────────────────────────────────────

async def _dispatch_step(
    user_id: str,
    app: str,
    action: str,
    resolved: dict,
    fallback_client: httpx.AsyncClient,
) -> Any:
    """Dispatch a single resolved step to the right handler. Returns the step result."""
    handler = _OAUTH_HANDLERS.get((app, action))
    if handler:
        return await handler(user_id, resolved)

    if app == "slack" and action in _SLACK_ACTIONS:
        return await _slack_send(user_id, resolved, action)

    webhook_url = await zapier_store.get_webhook_url(user_id, app, action)
    if not webhook_url:
        raise ValueError(f"No handler or Zapier webhook configured for {app}.{action}")
    resp = await fallback_client.post(webhook_url, json=resolved)
    resp.raise_for_status()
    log.info("Zapier webhook fired for %s.%s → HTTP %s", app, action, resp.status_code)
    return None


async def _execute_steps(
    user_id: str,
    steps: list[dict[str, Any]],
    context: dict,
    fallback_client: httpx.AsyncClient,
    completed: list,
    failed: list,
    event_sink: list | None = None,
) -> None:
    """
    Recursively execute a list of steps, mutating context/completed/failed in place.
    event_sink: if provided, SSE-ready dicts are appended here for the stream path.
    """
    for i, step in enumerate(steps):
        app    = step.get("app", "")
        action = step.get("action", "")
        label  = f"{app}.{action}"

        if event_sink is not None:
            event_sink.append({"type": "step_start", "label": label})

        try:
            # ── Control flow ──────────────────────────────────────────────
            if app == "control":
                await _execute_control(
                    user_id, action, step, context,
                    fallback_client, completed, failed, event_sink,
                )
                continue

            # ── Resolve params (with context support) ─────────────────────
            resolved = await _resolve_params(user_id, step.get("params", {}), context)

            # ── Remap misrouted innate steps ──────────────────────────────
            # Gemma sometimes hallucinates innate.<action> when the action
            # belongs to a real app (e.g. innate.create_document → google_drive).
            if app == "innate" and action not in _INNATE_ACTION_NAMES:
                remapped = _INNATE_REMAP.get(action)
                if remapped:
                    log.warning(
                        "remapping hallucinated innate.%s → %s.%s",
                        action, remapped, action,
                    )
                    app = remapped
                    label = f"{app}.{action}"

            # ── Innate actions ────────────────────────────────────────────
            if app == "innate":
                result = await execute_innate(user_id, action, resolved, context)
            else:
                result = await _dispatch_step(user_id, app, action, resolved, fallback_client)

            # Store output in context if output_key is set.
            output_key = step.get("output_key")
            if output_key and result is not None:
                context[output_key] = result

            completed.append({"step": label, "params": resolved})
            if event_sink is not None:
                event_sink.append({"type": "step_done", "label": label, "params": resolved})

        except Exception as exc:
            log.error("%s failed: %s", label, exc, exc_info=True)
            failed.append({"step": label, "error": str(exc)})
            if event_sink is not None:
                event_sink.append({"type": "step_error", "label": label, "error": str(exc)})


async def _execute_control(
    user_id: str,
    action: str,
    step: dict,
    context: dict,
    fallback_client: httpx.AsyncClient,
    completed: list,
    failed: list,
    event_sink: list | None,
) -> None:
    if action == "if":
        cond = bool(evaluate_condition(step.get("condition", ""), context))
        branch = step.get("then", []) if cond else step.get("else", [])
        await _execute_steps(user_id, branch, context, fallback_client, completed, failed, event_sink)

    elif action == "while":
        max_iter = min(int(step.get("max_iterations", 20)), 100)
        for _ in range(max_iter):
            if not evaluate_condition(step.get("condition", ""), context):
                break
            await _execute_steps(
                user_id, step.get("steps", []), context,
                fallback_client, completed, failed, event_sink,
            )

    elif action == "for_each":
        items_ref = step.get("items", "")
        if isinstance(items_ref, str) and items_ref.startswith("context."):
            items = _resolve_context_path(items_ref[len("context."):], context)
        else:
            items = items_ref
        if not isinstance(items, (list, tuple)):
            raise ValueError(f"control.for_each: 'items' did not resolve to a list (got {type(items).__name__})")
        items = list(items)[:50]  # hard cap to prevent runaway API calls
        loop_var = step.get("loop_variable", "_item")
        for item in items:
            context[loop_var] = item
            await _execute_steps(
                user_id, step.get("steps", []), context,
                fallback_client, completed, failed, event_sink,
            )
        context.pop(loop_var, None)

    else:
        raise ValueError(f"control: unknown action '{action}'")


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def execute_workflow_stream(user_id: str, steps: list[dict[str, Any]]):
    """Async generator yielding SSE-ready dicts as each step executes."""
    import json as _json
    context: dict = {}
    completed: list = []
    failed: list = []
    event_sink: list = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as fallback_client:
        await _execute_steps(
            user_id, steps, context, fallback_client, completed, failed, event_sink,
        )

    # Yield all collected events (event_sink is populated synchronously during execution)
    idx = 0
    for event in event_sink:
        if event["type"] == "step_start":
            yield {"type": "step_start", "index": idx, "label": event["label"]}
        elif event["type"] == "step_done":
            yield {"type": "step_done", "index": idx, "params": event.get("params", {})}
            idx += 1
        elif event["type"] == "step_error":
            yield {"type": "step_error", "index": idx, "error": event["error"]}
            idx += 1

    status = "success" if not failed else ("failed" if not completed else "partial")
    yield {"type": "done", "status": status}


async def execute_workflow(user_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    context: dict = {}
    completed: list[dict] = []
    failed:    list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as fallback_client:
        await _execute_steps(
            user_id, steps, context, fallback_client, completed, failed,
        )

    status = "success" if not failed else ("failed" if not completed else "partial")
    return {
        "status":          status,
        "steps_completed": completed,
        "steps_failed":    failed,
    }
