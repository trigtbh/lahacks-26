"""
infer_classifier.py
Passes a user query to Gemma with their connected OAuth services as context.
Gemma reasons about whether the query involves a 3rd party integration,
checks it against the connected list, and flags services that are needed
but not connected (including ones we've never seen before).
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai.llm import generate_json
from token_store import list_connections


_SYSTEM = """\
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


async def infer_for_user(query: str, user_id: str) -> dict[str, Any]:
    """
    Answer a query using Gemma, with the user's connected OAuth services
    (from the oauth_tokens table) as context. Gemma reasons about 3rd party
    involvement and flags any missing integrations.
    """
    services = await list_connections(user_id)
    services_str = ", ".join(services) if services else "none"

    user_prompt = (
        f"User's connected services: {services_str}\n\n"
        f"Query: {query}"
    )

    result = await asyncio.to_thread(generate_json, _SYSTEM, user_prompt, 0.3)
    result["connected_services"] = services
    return result
