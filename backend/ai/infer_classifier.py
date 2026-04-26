"""
infer_classifier.py

Two-stage inference:
  Stage 1 — reason about whether the query involves a 3rd party integration,
             check against the user's connected oauth_tokens.
  Stage 2 — if a connected integration is required, break the task into
             specific substeps, each mapped to a real API call.
             If any substep needs info we don't have, flag it for clarification.
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai.llm import generate_json, generate_json_coerce, generate_text
from token_store import list_connections


# ─────────────────────────────────────────────────────────────
# Stage 1 — integration analysis
# ─────────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM = """\
You are a helpful assistant. For every query you receive, you must:

1. Reason about whether fulfilling it would require any third-party service or app \
(e.g. Gmail, Google Calendar, Slack, Notion, Spotify, Uber, DoorDash, a bank, \
a social network, any external API, etc.). Think carefully — do not rely on \
keyword matching. Consider what actually needs to happen to fulfill the request.

2. If a third-party service is required, check whether it appears in the \
user's connected services list. If it does not appear — even if it's a service \
we've never seen before — mark it as not connected.

3. Answer the query concisely and directly.

Respond ONLY with valid JSON (no markdown) in this exact shape:
{
  "response": "your answer to the query",
  "involves_third_party": true,
  "required_integrations": ["service_a", "service_b"],
  "connected": ["service_a"],
  "not_connected": ["service_b"]
}

If the query requires no third-party service, set involves_third_party to false \
and leave required_integrations, connected, and not_connected as empty arrays.\
"""


# ─────────────────────────────────────────────────────────────
# Stage 2 — substep planning with real API calls
# ─────────────────────────────────────────────────────────────

_API_REFERENCE = """
VERIFIED API REFERENCE — use only these endpoints:

=== GMAIL ===
Send email
  POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send
  Body: { "raw": "<base64url-encoded RFC 2822 MIME message>" }
  Required scope: gmail.send

List messages
  GET https://gmail.googleapis.com/gmail/v1/users/me/messages
  Query params: q (search string), maxResults, pageToken, labelIds[]

Get message
  GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}
  Query params: format (FULL | MINIMAL | RAW | METADATA)

=== GOOGLE CALENDAR ===
List events
  GET https://www.googleapis.com/calendar/v3/calendars/primary/events
  Query params: timeMin (RFC3339), timeMax (RFC3339), maxResults, orderBy, singleEvents

Create event
  POST https://www.googleapis.com/calendar/v3/calendars/primary/events
  Body: { start: {dateTime, timeZone}, end: {dateTime, timeZone}, summary, description,
          attendees: [{email}], location }

Patch event
  PATCH https://www.googleapis.com/calendar/v3/calendars/primary/events/{eventId}
  Body: only the fields to update (patch semantics)

=== SLACK ===
Post message
  POST https://slack.com/api/chat.postMessage
  Body: { channel: "<channel_id_or_name>", text: "<message>" }
  Required scope: chat:write

List conversations
  GET https://slack.com/api/conversations.list
  Query params: types (public_channel,private_channel,im), limit, exclude_archived

Open DM
  POST https://slack.com/api/conversations.open
  Body: { users: "<user_id>" }

=== NOTION ===
Create page
  POST https://api.notion.com/v1/pages
  Headers: Notion-Version: 2022-06-28
  Body: { parent: {page_id | database_id}, properties: {title: ...}, children: [...] }

Query database
  POST https://api.notion.com/v1/databases/{database_id}/query
  Headers: Notion-Version: 2022-06-28
  Body: { filter: {...}, sorts: [...], page_size: 100 }

Append blocks
  PATCH https://api.notion.com/v1/blocks/{block_id}/children
  Headers: Notion-Version: 2022-06-28
  Body: { children: [...block objects...] }

=== DOMINO'S (unofficial, reverse-engineered) ===
Find nearby stores
  GET https://order.dominos.com/power/store-locator?s={street}&c={city}&type=Delivery

Get store menu
  GET https://order.dominos.com/power/store/{storeId}/menu?lang=en&structured=true

Validate order
  POST https://order.dominos.com/power/validate-order
  Body: order object

Price order
  POST https://order.dominos.com/power/price-order
  Body: order object

Place order
  POST https://order.dominos.com/power/place-order
  Body: complete order object (customer info, payment, items, address)
"""

_PLAN_SYSTEM = (
    _API_REFERENCE
    + """

You are a task planner. Given a user query and a list of connected integrations,
break the task into the smallest possible concrete substeps.

Rules:
- Every substep that touches a third-party service MUST map to one specific API call
  from the reference above. Include the exact HTTP method and endpoint URL.
- Do NOT invent endpoints, parameters, or data that isn't in the reference.
- Do NOT include steps you don't have enough information to define precisely.
  Instead, set needs_clarification: true and write a specific question.
- Steps that require output from a previous step should reference it by index
  (e.g. "use event id from step 1").
- Non-API steps (e.g. "construct MIME email body", "extract event id from response")
  are fine — set api_call to null for those.

Respond ONLY with valid JSON (no markdown):
{
  "substeps": [
    {
      "index": 1,
      "description": "short description of what this step does",
      "api_call": {
        "service": "gmail",
        "method": "GET",
        "endpoint": "https://...",
        "params": {}
      },
      "needs_clarification": false,
      "clarification_question": null
    }
  ],
  "has_clarifications": false
}

If a substep does not involve an API call, set api_call to null.
If any substep needs clarification, set has_clarifications to true.
"""
)

_REPLAN_SYSTEM = (
    _API_REFERENCE
    + """

You are a task planner. The user provided clarifications to questions about a task.
Produce a revised, complete substep plan incorporating those answers.
Apply the same rules as before: every API substep must map to an exact endpoint from
the reference, nothing invented, no missing information.

You MUST respond with a single JSON object (not an array). Use exactly this shape:
{
  "substeps": [
    {
      "index": 1,
      "description": "short description",
      "api_call": {
        "service": "gmail",
        "method": "POST",
        "endpoint": "https://...",
        "params": {}
      },
      "needs_clarification": false,
      "clarification_question": null
    }
  ],
  "has_clarifications": false
}

If a substep does not involve an API call, set api_call to null.
If any substep still needs clarification, set has_clarifications to true.
Do NOT return a bare array — always wrap substeps inside the object above.
"""
)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

async def infer_for_user(query: str, user_id: str) -> dict[str, Any]:
    """
    Stage 1 + Stage 2.
    Returns the integration analysis and, if a connected integration is
    involved, a substep plan with specific API calls.
    """
    services = await list_connections(user_id)
    services_str = ", ".join(services) if services else "none"

    # Stage 1 — integration analysis
    analysis = await asyncio.to_thread(
        generate_json,
        _ANALYSIS_SYSTEM,
        f"User's connected services: {services_str}\n\nQuery: {query}",
        0.3,
    )
    analysis["connected_services"] = services

    # Stage 2 — substep planning (only if there's a connected integration)
    connected_required = analysis.get("connected", [])
    if analysis.get("involves_third_party") and connected_required:
        plan = await asyncio.to_thread(
            generate_json,
            _PLAN_SYSTEM,
            (
                f"User's connected integrations: {', '.join(connected_required)}\n\n"
                f"Task: {query}"
            ),
            0.2,
        )
        analysis["substeps"] = plan.get("substeps", [])
        analysis["has_clarifications"] = plan.get("has_clarifications", False)
    else:
        analysis["substeps"] = []
        analysis["has_clarifications"] = False

    return analysis


async def clarify_for_user(
    original_query: str,
    user_id: str,
    previous_substeps: list[dict],
    clarifications: dict[str, str],
) -> dict[str, Any]:
    """
    Stage 2 re-run after the user has answered clarification questions.
    Returns a revised substep plan.
    """
    services = await list_connections(user_id)
    connected_required = [
        s["api_call"]["service"]
        for s in previous_substeps
        if s.get("api_call") and s.get("needs_clarification")
    ]

    qa_text = "\n".join(
        f"Q: {q}\nA: {a}" for q, a in clarifications.items()
    )

    user_prompt = (
        f"Original task: {original_query}\n\n"
        f"Connected integrations: {', '.join(services)}\n\n"
        f"Previous substeps:\n{previous_substeps}\n\n"
        f"User's clarifications:\n{qa_text}"
    )

    plan = await asyncio.to_thread(
        generate_json_coerce, _REPLAN_SYSTEM, user_prompt, "substeps", 0.2
    )

    return {
        "substeps": plan.get("substeps", []),
        "has_clarifications": plan.get("has_clarifications", False),
        "connected_services": services,
    }
