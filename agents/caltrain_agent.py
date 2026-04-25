"""
Caltrain agent — deployed on Agentverse.

Answers questions about Caltrain schedules and delays using the 511 SF Bay API.
Run this file separately to deploy the agent:
    python agents/caltrain_agent.py
"""

import os
import logging
import httpx
from uagents import Agent, Context
from agents.base_agent import UserQuery, AgentReply

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SF_511_API_KEY = os.environ.get("SF_511_API_KEY", "")
SF_511_BASE = "https://api.511.org/transit"

agent = Agent(
    name="caltrain",
    seed=os.environ.get("CALTRAIN_AGENT_SEED", "caltrain-agent-seed-lahacks-26"),
    port=8010,
    endpoint=["http://localhost:8010/submit"],
    agentverse="https://agentverse.ai",
)


async def _get_departures(origin: str = "22nd Street") -> str:
    """Fetch next Caltrain departures from a stop via 511 API."""
    if not SF_511_API_KEY:
        return "511 API key not configured."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SF_511_BASE}/StopMonitoring",
                params={
                    "api_key": SF_511_API_KEY,
                    "agency": "CT",
                    "stopCode": origin,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            visits = (
                data.get("ServiceDelivery", {})
                    .get("StopMonitoringDelivery", {})
                    .get("MonitoredStopVisit", [])
            )
            if not visits:
                return f"No upcoming Caltrain departures found from {origin}."
            lines = []
            for v in visits[:3]:
                journey = v.get("MonitoredVehicleJourney", {})
                call = journey.get("MonitoredCall", {})
                dest = journey.get("DestinationName", "?")
                aimed = call.get("AimedDepartureTime", "?")
                expected = call.get("ExpectedDepartureTime", aimed)
                lines.append(f"To {dest}: departs {expected}")
            return "\n".join(lines)
    except Exception as e:
        logger.error(f"511 API error: {e}")
        return f"Could not fetch schedule: {e}"


@agent.on_message(model=UserQuery)
async def handle_query(ctx: Context, sender: str, msg: UserQuery):
    logger.info(f"[caltrain] query from {sender}: {msg.text!r}")
    text = msg.text.lower()

    if any(w in text for w in ["next", "depart", "when", "schedule", "train"]):
        reply_text = await _get_departures()
    else:
        reply_text = (
            "I'm the Caltrain agent. Ask me about upcoming departures, "
            "schedules, or delays."
        )

    await ctx.send(sender, AgentReply(text=reply_text, user_id=msg.user_id))


if __name__ == "__main__":
    agent.run()
