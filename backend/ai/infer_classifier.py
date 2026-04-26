"""
infer_classifier.py
Integration-aware classifier. Instead of a predefined skill schema, Gemma is
told which OAuth services the user has connected (from the oauth_tokens table)
and freely decides what steps are needed and whether each requires an integration.
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai.llm import generate_json
from token_store import list_connections


_INFER_SYSTEM_TEMPLATE = """\
You are a workflow planning assistant. Given a user command, break it into executable steps.

The user has the following OAuth-connected services: {services}

For each step:
- If it requires a third-party service (e.g. Gmail, Google Calendar, Slack, Notion, Domino's, etc.),
  set "app" to the service name in lowercase (e.g. "gmail", "google_calendar", "slack", "notion", "dominos").
- If the required service is NOT in the connected list above, set "integration_available" to false.
- If the step does not need any external service (math, formatting, waiting, variable manipulation, etc.),
  set "app" to "innate" and "requires_integration" to false.

Output ONLY valid JSON in this exact format — no markdown, no extra text:
{{
  "trigger_phrase": "short phrase describing the user intent",
  "steps": [
    {{
      "description": "human-readable description of this step",
      "app": "service_name or innate",
      "action": "action_name",
      "params": {{}},
      "requires_integration": true,
      "integration_available": true
    }}
  ],
  "involves_third_party": true,
  "missing_integrations": [],
  "confidence": 0.9
}}
"""


async def infer_for_user(transcript: str, user_id: str) -> dict[str, Any]:
    """
    Classify a command into a workflow by checking the oauth_tokens table
    for the specific user — no predefined skill schema is used.
    """
    services = await list_connections(user_id)
    services_str = ", ".join(services) if services else "none"
    system_prompt = _INFER_SYSTEM_TEMPLATE.format(services=services_str)
    user_prompt = f"Command: {transcript}"

    result = await asyncio.to_thread(generate_json, system_prompt, user_prompt, 0.2)
    result["_connected_services"] = services
    return result
