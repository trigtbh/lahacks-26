"""
Agentverse integration: agent discovery + uAgents gateway messaging.

Discovery:  POST https://agentverse.ai/v1/search/agents
Messaging:  local gateway uAgent communicates via uAgents protocol

Cross-loop bridge pattern:
  - gateway.run() spins its own asyncio loop in a daemon thread
  - outgoing messages go through a stdlib queue.Queue (thread-safe)
  - on_interval drains the queue and calls ctx.send() inside gateway's loop
  - replies come back via on_message; delivered to FastAPI's loop via
    _fastapi_loop.call_soon_threadsafe(future.set_result, text)
"""

import asyncio
import logging
import os
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from uagents import Agent, Context, Model

logger = logging.getLogger(__name__)

AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY", "")
_SEARCH_URL = "https://agentverse.ai/v1/search/agents"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {AGENTVERSE_API_KEY}",
        "Content-Type": "application/json",
    }


# ── Message models ────────────────────────────────────────────────────────────

class UserQuery(Model):
    """Used with our own agents (Caltrain etc.)."""
    text: str
    user_id: str

class AgentReply(Model):
    """Response from our own agents."""
    text: str
    user_id: str

class TextContent(Model):
    """Chat Protocol content block used by community agents."""
    type: str
    text: str

class ChatMessage(Model):
    """Chat Protocol wrapper used by ASI:One-compatible community agents."""
    timestamp: str
    msg_id: str
    content: list[TextContent]


# ── Cross-loop state ──────────────────────────────────────────────────────────

_outgoing: queue.Queue = queue.Queue()          # (address, text, user_id, use_query) — thread-safe
_pending: dict[str, asyncio.Future] = {}        # user_id → Future (lives in FastAPI's loop)
_agent_to_user: dict[str, str] = {}             # agent_address → user_id (for ChatMessage replies)
_fastapi_loop: Optional[asyncio.AbstractEventLoop] = None


def _resolve(user_id: str, text: str) -> None:
    """Thread-safely deliver a reply to the waiting Future in FastAPI's loop."""
    future = _pending.pop(user_id, None)
    if future and _fastapi_loop and not future.done():
        _fastapi_loop.call_soon_threadsafe(future.set_result, text)


# ── Gateway agent ─────────────────────────────────────────────────────────────

gateway = Agent(
    name="flux-gateway",
    seed=os.environ.get("GATEWAY_SEED", "flux-gateway-seed-lahacks-26"),
    port=8001,
    endpoint=["http://localhost:8001/submit"],
)


@gateway.on_interval(period=0.1)
async def _flush_outgoing(ctx: Context) -> None:
    """Drain the outgoing queue and send via ctx.send(). Runs in gateway's loop."""
    while True:
        try:
            address, text, user_id, use_query = _outgoing.get_nowait()
        except queue.Empty:
            break

        if use_query:
            msg = UserQuery(text=text, user_id=user_id)
            logger.info(f"[gateway] sent UserQuery to {address} user={user_id}")
        else:
            msg = ChatMessage(
                timestamp=datetime.now(timezone.utc).isoformat(),
                msg_id=str(uuid.uuid4()),
                content=[TextContent(type="text", text=text)],
            )
            _agent_to_user[address] = user_id
            logger.info(f"[gateway] sent ChatMessage to {address} user={user_id}")
        await ctx.send(address, msg)


@gateway.on_message(model=AgentReply)
async def _on_agent_reply(ctx: Context, sender: str, msg: AgentReply) -> None:
    """Reply from our own agents (UserQuery/AgentReply schema)."""
    logger.info(f"[gateway] AgentReply from {sender}: {msg.text!r}")
    _resolve(msg.user_id, msg.text)


@gateway.on_message(model=ChatMessage)
async def _on_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    """Reply from community Chat Protocol agents."""
    text = next((c.text for c in msg.content if c.type == "text" and c.text), "")
    user_id = _agent_to_user.pop(sender, None)
    logger.info(f"[gateway] ChatMessage from {sender} user={user_id}: {text!r}")
    if user_id:
        _resolve(user_id, text)


def start_gateway() -> None:
    """
    Capture FastAPI's running event loop, then start the gateway in a daemon
    thread. Must be called from inside an async context (e.g. FastAPI lifespan).
    """
    global _fastapi_loop
    _fastapi_loop = asyncio.get_running_loop()
    t = threading.Thread(target=gateway.run, daemon=True, name="uagents-gateway")
    t.start()
    logger.info(f"[gateway] started — address: {gateway.address}")


async def send_to_agent(
    agent_address: str,
    message: str,
    user_id: str,
    timeout: float = 60.0,
) -> str:
    """
    Enqueue a message for an agent and await the reply.
    Uses UserQuery for known/custom agents, ChatMessage for community agents.
    Safe to call from FastAPI's async context.
    """
    known_addresses = {addr for addr, _ in KNOWN_AGENTS.values()}
    use_query = agent_address in known_addresses

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[user_id] = future
    _outgoing.put_nowait((agent_address, message, user_id, use_query))

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(user_id, None)
        _agent_to_user.pop(agent_address, None)
        raise TimeoutError(f"No reply from {agent_address} within {timeout}s")


# ── Known agents (fallback when Agentverse search doesn't find them) ──────────
# Add your deployed agent addresses here after deploying to Agentverse.

KNOWN_AGENTS: dict[str, tuple[str, str]] = {
    # "spoken name": ("agent1q...", "Display Name")
    "caltrain": ("agent1qtuuyttz8ujuxceq0gllcerlksjneenrh2mfcm67st8qrm9lzzh3cd7f9h6", "Caltrain"),
}


def _match_known(name: str) -> Optional[tuple[str, str]]:
    """Case-insensitive substring match against KNOWN_AGENTS keys."""
    name_lower = name.lower()
    for key, value in KNOWN_AGENTS.items():
        if key in name_lower or name_lower in key:
            return value
    return None


# ── Agent discovery ───────────────────────────────────────────────────────────

async def search_agents(name: str, limit: int = 5) -> list[dict]:
    """POST /v1/search/agents — semantic search by name."""
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
    """
    Find best matching agent by name.
    Checks KNOWN_AGENTS first, then falls back to Agentverse search.
    Returns (agent_address, display_name) or None.
    """
    # 1. Check hardcoded registry (instant, no API call)
    known = _match_known(name)
    if known:
        logger.info(f"[find_agent] {name!r} matched known agent: {known[1]}")
        return known

    # 2. Fall back to Agentverse search
    agents = await search_agents(name)
    if not agents:
        return None
    agent = agents[0]
    address = agent.get("address") or agent.get("agent_address")
    display_name = agent.get("name") or name
    if not address:
        return None
    return address, display_name
