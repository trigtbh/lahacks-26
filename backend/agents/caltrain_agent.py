"""
Caltrain agent — deploy this on Agentverse as a Hosted Agent.

Steps:
  1. Go to agentverse.ai → Create Agent → Hosted Agent
  2. Paste this file's contents into the editor
  3. Add secret: SF_511_API_KEY (get one free at 511.org/open-data/token)
  4. Click Start — copy the agent address (agent1q...)
  5. Add that address to KNOWN_AGENTS in agentverse_client.py

Uses the Chat Protocol so it works with ASI:One and our gateway.
"""

import os
import uuid
import logging
import httpx
from datetime import datetime, timezone

from uagents import Agent, Context
from uagents.experimental.quota import AgentQuotaProtocol, RateLimit
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_version,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SF_511_API_KEY = os.environ.get("SF_511_API_KEY", "")
SF_511_BASE    = "https://api.511.org/transit"

# Map common spoken stop names to 511 stop codes
STOP_CODES = {
    "san francisco":  "70011",
    "sf":             "70011",
    "22nd street":    "70021",
    "22nd":           "70021",
    "millbrae":       "70061",
    "palo alto":      "70211",
    "mountain view":  "70231",
    "san jose":       "70261",
    "diridon":        "70261",
    "santa clara":    "70271",
    "sunnyvale":      "70241",
    "redwood city":   "70161",
    "san mateo":      "70091",
}

agent = Agent(
    name="caltrain",
    readme="""
## Caltrain Schedule Agent
Ask me about upcoming Caltrain departures, schedules, and service status.
Examples: "When is the next train to San Francisco?" / "Next train from Palo Alto?"
""",
)

proto = AgentQuotaProtocol(
    name="caltrain-chat",
    version=chat_protocol_version,
    rate_limit=RateLimit(window_size_minutes=1, max_requests=10),
)


async def _next_departures(query: str) -> str:
    """Parse stop from query and fetch next departures via 511 API."""
    query_lower = query.lower()

    origin_code = None
    for name, code in STOP_CODES.items():
        if name in query_lower:
            origin_code = code
            break

    if not origin_code:
        return (
            "I can look up departures from SF, 22nd Street, Millbrae, Palo Alto, "
            "Mountain View, San Jose, Santa Clara, Sunnyvale, Redwood City, or San Mateo. "
            "Which station are you at?"
        )

    if not SF_511_API_KEY:
        return "511 API key not configured — ask your administrator to set SF_511_API_KEY."

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SF_511_BASE}/StopMonitoring",
                params={
                    "api_key": SF_511_API_KEY,
                    "agency":  "CT",
                    "stopCode": origin_code,
                    "format":  "json",
                },
            )
            resp.raise_for_status()
            visits = (
                resp.json()
                    .get("ServiceDelivery", {})
                    .get("StopMonitoringDelivery", {})
                    .get("MonitoredStopVisit", [])
            )
        if not visits:
            return "No upcoming Caltrain departures found. Service may be suspended."

        lines = []
        for v in visits[:3]:
            journey = v.get("MonitoredVehicleJourney", {})
            call    = journey.get("MonitoredCall", {})
            dest    = journey.get("DestinationName", "Unknown")
            exp     = call.get("ExpectedDepartureTime") or call.get("AimedDepartureTime", "?")
            lines.append(f"To {dest}: departs {exp}")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"511 API error: {e}")
        return f"Could not fetch schedule: {e}"


@proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # Acknowledge receipt
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )

    text = next((c.text for c in msg.content if isinstance(c, TextContent)), "").strip()
    logger.info(f"[caltrain] from {sender}: {text!r}")

    reply_text = await _next_departures(text) if text else (
        "Ask me about Caltrain departures — e.g. 'next train to SF'."
    )

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid.uuid4(),
            content=[TextContent(type="text", text=reply_text)],
        ),
    )


agent.include(proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
