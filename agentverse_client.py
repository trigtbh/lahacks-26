"""
Agentverse integration: agent discovery + message routing.

Discovery:  GET https://agentverse.ai/v1/almanac/agents?search=<name>
Messaging:  local gateway uAgent sends/receives via uAgents protocol
"""

import asyncio
import logging
import os
from typing import Optional

import httpx
from uagents import Agent, Context, Model

logger = logging.getLogger(__name__)

AGENTVERSE_API = "https://agentverse.ai"
AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY", "")

# ── Message schemas ──────────────────────────────────────────────────────────

class UserQuery(Model):
    text: str
    user_id: str

class AgentReply(Model):
    text: str
    user_id: str

# ── Gateway agent ────────────────────────────────────────────────────────────

gateway = Agent(
    name="flux-gateway",
    seed=os.environ.get("GATEWAY_SEED", "flux-gateway-seed-lahacks-26"),
    port=8001,
    endpoint=["http://localhost:8001/submit"],
)

# Pending futures: user_id -> Future[str]
_pending: dict[str, asyncio.Future] = {}


@gateway.on_message(model=AgentReply)
async def _on_reply(ctx: Context, sender: str, msg: AgentReply):
    future = _pending.pop(msg.user_id, None)
    if future and not future.done():
        future.set_result(msg.text)
        logger.info(f"[gateway] reply from {sender} for user={msg.user_id}: {msg.text!r}")


async def send_to_agent(
    agent_address: str,
    message: str,
    user_id: str,
    timeout: float = 15.0,
) -> str:
    """Send a message to an agent and wait for AgentReply."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[user_id] = future

    # gateway.send is non-blocking; the reply comes via _on_reply
    await gateway.send(agent_address, UserQuery(text=message, user_id=user_id))

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(user_id, None)
        raise TimeoutError(f"No reply from {agent_address} within {timeout}s")


# ── Agent discovery ──────────────────────────────────────────────────────────

async def search_agent(name: str) -> list[dict]:
    """Search Agentverse almanac for agents matching name. Returns list of agent dicts."""
    headers = {}
    if AGENTVERSE_API_KEY:
        headers["Authorization"] = f"Bearer {AGENTVERSE_API_KEY}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{AGENTVERSE_API}/v1/almanac/agents",
            params={"search": name},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("agents", data) if isinstance(data, dict) else data


async def find_agent_address(name: str) -> Optional[tuple[str, str]]:
    """
    Find the best matching agent on Agentverse by name.
    Returns (address, display_name) or None.
    """
    try:
        agents = await search_agent(name)
    except Exception as e:
        logger.error(f"[agentverse] search failed for {name!r}: {e}")
        return None

    if not agents:
        return None

    # Pick the first result (closest match)
    agent = agents[0]
    address = agent.get("address") or agent.get("agent_address")
    display_name = agent.get("name") or name
    return address, display_name


def start_gateway():
    """Start the gateway agent in a background thread (call once at app startup)."""
    import threading
    t = threading.Thread(target=gateway.run, daemon=True)
    t.start()
    logger.info(f"[gateway] started — address: {gateway.address}")
