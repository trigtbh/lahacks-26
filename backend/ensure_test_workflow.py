"""
ensure_test_workflow.py

Seed a simple test workflow in MongoDB if it does not already exist.

This is useful when you want to test workflow execution directly from the
mobile app without first relying on workflow creation/classification.

Usage:
    python ensure_test_workflow.py --user ved29022004@gmail.com

Optional:
    --trigger "I'm running late"
    --minutes 15
"""

from __future__ import annotations

import argparse
import asyncio
import json

from db import MONGO_ENABLED
import workflow_store


def _build_steps(user_id: str, minutes: int) -> list[dict]:
    # Keep this compatible with the current executor implementation.
    # Gmail sends to the same user so we can validate execution without
    # depending on extra contact resolvers.
    return [
        {
            "app": "google_calendar",
            "action": "push_event",
            "params": {
                "by_minutes": minutes,
            },
        },
        {
            "app": "gmail",
            "action": "send_email",
            "params": {
                "to": user_id,
                "subject": "Running late",
                "body": f"I'm running {minutes} minutes late to my next meeting.",
            },
        },
    ]


async def ensure_workflow(user_id: str, trigger_phrase: str, minutes: int) -> None:
    if not MONGO_ENABLED:
        raise SystemExit("MongoDB is disabled. Check backend/.env and db.py settings.")

    existing = await workflow_store.find_by_trigger(user_id, trigger_phrase)
    if existing:
        existing_id = str(existing.get("_id", ""))
        print("Workflow already exists.")
        print(json.dumps({
            "workflow_id": existing_id,
            "user_id": user_id,
            "trigger_phrase": existing.get("trigger_phrase", ""),
            "steps": existing.get("steps", []),
        }, indent=2, default=str))
        return

    steps = _build_steps(user_id, minutes)
    workflow_id = await workflow_store.save_workflow(
        user_id=user_id,
        trigger_phrase=trigger_phrase,
        steps=steps,
    )
    print("Workflow created.")
    print(json.dumps({
        "workflow_id": workflow_id,
        "user_id": user_id,
        "trigger_phrase": trigger_phrase,
        "steps": steps,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True, help="User id / email used by the backend tokens")
    parser.add_argument("--trigger", default="I'm running late", help="Trigger phrase to seed")
    parser.add_argument("--minutes", type=int, default=15, help="Minutes to push the next event")
    args = parser.parse_args()

    asyncio.run(ensure_workflow(args.user, args.trigger, args.minutes))


if __name__ == "__main__":
    main()
