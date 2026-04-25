"""
Agentverse AI Engine REST API client.

Community agents are reached via the AI Engine, which handles routing to any
registered agent by name/description. No uAgents SDK or gateway needed.

Flow per query:
  1. create_session(user_id)       → session_id
  2. send_message(session_id, msg) → (no return)
  3. poll_response(session_id)     → response text
  4. delete_session(session_id)    → cleanup on disconnect
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY", "")
_AI_ENGINE = "https://agentverse.ai/v1beta1/engine/chat"
_ALMANAC   = "https://agentverse.ai/v1/almanac/agents"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {AGENTVERSE_API_KEY}",
        "Content-Type": "application/json",
    }


# ── Session lifecycle ─────────────────────────────────────────────────────────

async def create_session(user_id: str) -> str:
    """Open an AI Engine chat session. Returns session_id."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_AI_ENGINE}/sessions",
            headers=_headers(),
            json={"email": user_id},
        )
        resp.raise_for_status()
        return resp.json()["session_id"]


async def send_message(session_id: str, message: str) -> None:
    """Submit a user message to an existing AI Engine session."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_AI_ENGINE}/sessions/{session_id}/submit",
            headers=_headers(),
            json={
                "session_id": session_id,
                "payload": {
                    "type": "user_message",
                    "user_message": message,
                },
            },
        )
        resp.raise_for_status()


async def poll_response(
    session_id: str,
    timeout: float = 30.0,
    poll_interval: float = 1.5,
) -> Optional[str]:
    """
    Poll until the AI Engine returns an agent reply.
    Returns the response text, or None on timeout.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    async with httpx.AsyncClient(timeout=15) as client:
        while loop.time() < deadline:
            resp = await client.get(
                f"{_AI_ENGINE}/sessions/{session_id}/responses",
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # The API may return a list or {"agent_response": [...]}
            messages: list = data if isinstance(data, list) else data.get("agent_response", [])

            for msg in messages:
                kind = msg.get("type") or msg.get("message_type", "")
                text = (
                    msg.get("agent_message")
                    or msg.get("text")
                    or msg.get("content")
                    or ""
                )
                if kind in ("agent_message", "agent_response") and text:
                    return text
                # Some agents signal completion without a message text
                if kind in ("stop", "end", "agent_confirmation"):
                    return text or "(done)"

            await asyncio.sleep(poll_interval)

    return None


async def delete_session(session_id: str) -> None:
    """Delete an AI Engine session (best-effort, ignore errors)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{_AI_ENGINE}/sessions/{session_id}",
                headers=_headers(),
            )
    except Exception:
        pass


# ── High-level query helper ───────────────────────────────────────────────────

async def query_agent(
    message: str,
    user_id: str,
    session_id: Optional[str] = None,
    agent_context: Optional[str] = None,
    timeout: float = 30.0,
) -> tuple[str, str]:
    """
    Send a message to the AI Engine and return (response_text, session_id).

    Pass the same session_id on follow-up messages to continue the conversation.
    agent_context is prepended to the first message so the AI Engine knows which
    agent/service the user wants (e.g. "Caltrain schedule: when is the next train?").
    """
    if not AGENTVERSE_API_KEY:
        return "AGENTVERSE_API_KEY is not set.", session_id or ""

    new_session = session_id is None
    if new_session:
        session_id = await create_session(user_id)

    # On a new session, prefix the message with the agent context so the AI
    # Engine can route to the right registered agent.
    payload = f"{agent_context}: {message}" if (new_session and agent_context) else message

    await send_message(session_id, payload)
    response = await poll_response(session_id, timeout=timeout)

    if response is None:
        response = "The agent didn't respond in time. Try again."

    return response, session_id


# ── Agent discovery ───────────────────────────────────────────────────────────

async def search_agent(name: str) -> list[dict]:
    """Search Agentverse almanac for agents matching name."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _ALMANAC,
                params={"search": name},
                headers=_headers(),
            )
            if not resp.is_success:
                return []
            data = resp.json()
            return data.get("agents", data) if isinstance(data, dict) else data
    except Exception as e:
        logger.error(f"[agentverse] almanac search error: {e}")
        return []


async def find_agent_name(query: str) -> str:
    """
    Resolve a user-spoken agent name to a canonical display name.
    Falls back to the raw query string if the almanac search fails.
    """
    agents = await search_agent(query)
    if agents:
        return agents[0].get("name") or query
    return query


def start_gateway() -> None:
    """No-op — gateway replaced by AI Engine REST API."""
