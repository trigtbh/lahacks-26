"""
Agentverse integration: agent discovery + ASI:ONE chat completions.

Discovery:  POST https://agentverse.ai/v1/search/agents
Messaging:  POST https://api.asi1.ai/v1/chat/completions  (agent_address field)

Both APIs use the same AGENTVERSE_API_KEY Bearer token.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY", "")
_SEARCH_URL = "https://agentverse.ai/v1/search/agents"
_ASI1_CHAT_URL = "https://api.asi1.ai/v1/chat/completions"


def _auth_headers(session_id: Optional[str] = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {AGENTVERSE_API_KEY}",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["x-session-id"] = session_id
    return headers


# ── Agent messaging via ASI:ONE ───────────────────────────────────────────────

async def send_to_agent(
    agent_address: str,
    message: str,
    user_id: str,
    timeout: float = 60.0,
) -> str:
    """
    Chat with an Agentverse agent via the ASI:ONE Chat Completions API.
    Uses user_id as the session ID to persist conversation context across calls.
    """
    if not AGENTVERSE_API_KEY:
        raise RuntimeError("AGENTVERSE_API_KEY not set")

    payload = {
        "model": "asi1",
        "agent_address": agent_address,
        "messages": [{"role": "user", "content": message}],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            _ASI1_CHAT_URL,
            headers=_auth_headers(session_id=user_id),
            json=payload,
        )

    if not resp.is_success:
        logger.error(f"[asi1] {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"ASI:ONE API error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error(f"[asi1] unexpected response shape: {data}")
        raise RuntimeError(f"Unexpected ASI:ONE response: {e}") from e


# ── Known agents ──────────────────────────────────────────────────────────────

KNOWN_AGENTS: dict[str, tuple[str, str]] = {
    "caltrain": ("agent1qtuuyttz8ujuxceq0gllcerlksjneenrh2mfcm67st8qrm9lzzh3cd7f9h6", "Caltrain"),
}


def _match_known(name: str) -> Optional[tuple[str, str]]:
    name_lower = name.lower()
    for key, value in KNOWN_AGENTS.items():
        if key in name_lower or name_lower in key:
            return value
    return None


# ── Agent discovery ───────────────────────────────────────────────────────────

async def search_agents(name: str, limit: int = 5) -> list[dict]:
    if not AGENTVERSE_API_KEY:
        logger.warning("[search] AGENTVERSE_API_KEY not set")
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _SEARCH_URL,
                headers=_auth_headers(),
                json={"search_text": name, "sort": "relevancy", "limit": limit},
            )
            if not resp.is_success:
                logger.warning(f"[search] {resp.status_code}: {resp.text[:200]}")
                return []
            return resp.json().get("agents", [])
    except Exception as e:
        logger.error(f"[search] error for {name!r}: {e}")
        return []


async def find_agent(name: str) -> Optional[tuple[str, str]]:
    known = _match_known(name)
    if known:
        logger.info(f"[find_agent] {name!r} matched known agent: {known[1]}")
        return known

    agents = await search_agents(name)
    if not agents:
        return None
    agent = agents[0]
    address = agent.get("address") or agent.get("agent_address")
    display_name = agent.get("name") or name
    if not address:
        return None
    return address, display_name
