"""
infer_classifier.py
Passes a user query to Gemma with their connected OAuth services as context.
Gemma answers directly — no skill schema, no structured workflow output.
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai.llm import generate_text
from token_store import list_connections


_SYSTEM = """\
You are a helpful assistant. You will be given a list of third-party services \
the user has connected to their account, and a query or command from the user.

Answer the query or carry out the request directly and concisely. \
When the query asks whether something involves a third-party integration, \
answer by checking the provided connected services list — do not assume any \
service is available unless it appears in that list.\
"""


async def infer_for_user(query: str, user_id: str) -> dict[str, Any]:
    """
    Answer a query using Gemma, with the user's connected OAuth services
    (from the oauth_tokens table) provided as context.
    """
    services = await list_connections(user_id)
    services_str = ", ".join(services) if services else "none"

    user_prompt = (
        f"Connected services for this user: {services_str}\n\n"
        f"Query: {query}"
    )

    response = await asyncio.to_thread(generate_text, _SYSTEM, user_prompt, 0.7)

    return {
        "response": response,
        "connected_services": services,
    }
