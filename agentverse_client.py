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

class TextContent(Model):
    type: str
    text: str

class ChatMessage(Model):
    timestamp: str
    msg_id: str
    content: list[TextContent]

class ChatAcknowledgement(Model):
    timestamp: str
    acknowledged_msg_id: str


# ── Cross-loop state ──────────────────────────────────────────────────────────

_outgoing: queue.Queue = queue.Queue()          # (address, text, user_id) — thread-safe
_pending: dict[str, asyncio.Future] = {}        # user_id → Future (lives in FastAPI's loop)
_agent_to_user: dict[str, str] = {}             # agent_address → user_id
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
    mailbox=True,
    loop=asyncio.new_event_loop(),
)


@gateway.on_interval(period=0.1)
async def _flush_outgoing(ctx: Context) -> None:
    """Drain the outgoing queue and send ChatMessage. Runs in gateway's loop."""
    while True:
        try:
            address, text, user_id = _outgoing.get_nowait()
        except queue.Empty:
            break

        msg = ChatMessage(
            timestamp=datetime.now(timezone.utc).isoformat(),
            msg_id=str(uuid.uuid4()),
            content=[TextContent(type="text", text=text)],
        )
        _agent_to_user[address] = user_id
        logger.info(f"[gateway] sent ChatMessage to {address} user={user_id}")
        await ctx.send(address, msg)


@gateway.on_message(model=ChatAcknowledgement)
async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    logger.info(f"[gateway] ChatAck from {sender} ack={msg.acknowledged_msg_id}")


@gateway.on_message(model=ChatMessage)
async def _on_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
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
    timeout: float = 20.0,
) -> str:
    """
    Enqueue a ChatMessage for an agent and await the reply.
    Safe to call from FastAPI's async context.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[user_id] = future
    _outgoing.put_nowait((agent_address, message, user_id))

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(user_id, None)
        _agent_to_user.pop(agent_address, None)
        raise TimeoutError(f"No reply from {agent_address} within {timeout}s")


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
