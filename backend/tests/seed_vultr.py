"""
tests/seed_vultr.py
One-time script: seed the 3 canonical demo workflows into Vultr's MongoDB.

Usage:
    python tests/seed_vultr.py
    # or against a different server:
    BASE=http://149.248.10.229:8000 USER=ved29022004@gmail.com python tests/seed_vultr.py
"""

import asyncio
import os
import httpx

BASE = os.getenv("BASE", "http://149.248.10.229:8000")
USER = os.getenv("USER", "ved29022004@gmail.com")

WORKFLOWS = [
    {
        "trigger_phrase": "I'm running late",
        "steps": [
            {
                "app": "google_calendar",
                "action": "push_event",
                "params": {"by_minutes": 15},
                "output_key": "calendar_result",
            },
            {
                "app": "gmail",
                "action": "send_email",
                "params": {
                    "to": "organizer@example.com",
                    "subject": "Running 15 minutes late",
                    "body": "Hey, I'm running about 15 minutes late to our meeting. Sorry for the inconvenience!",
                },
            },
        ],
    },
    {
        "trigger_phrase": "morning brief",
        "steps": [
            {
                "app": "innate",
                "action": "get_datetime",
                "params": {"format": "iso"},
                "output_key": "today",
            },
            {
                "app": "innate",
                "action": "datetime_math",
                "params": {"base_time": "context.today", "operation": "add", "amount": 6, "unit": "hours"},
                "output_key": "start_window",
            },
            {
                "app": "innate",
                "action": "datetime_math",
                "params": {"base_time": "context.today", "operation": "add", "amount": 9, "unit": "hours"},
                "output_key": "end_window",
            },
            {
                "app": "gmail",
                "action": "search_email",
                "params": {"query": "is:unread after:context.start_window before:context.end_window", "max_results": 10},
                "output_key": "emails",
            },
            {
                "app": "innate",
                "action": "format_list",
                "params": {"items": "context.emails", "field": "subject"},
                "output_key": "subjects",
            },
        ],
    },
    {
        "trigger_phrase": "I'm done with the day",
        "steps": [
            {
                "app": "google_drive",
                "action": "read_document",
                "params": {"file_name": "Standup -- Transcript"},
                "output_key": "transcript",
            },
            {
                "app": "innate",
                "action": "ai_summarize",
                "params": {
                    "content": "context.transcript.text",
                    "instruction": "Write a concise standup summary: what was accomplished today, any blockers, and what's planned next.",
                },
                "output_key": "standup",
            },
            {
                "app": "slack",
                "action": "send_channel",
                "params": {"channel": "#general", "message": "context.standup"},
            },
            {
                "app": "innate",
                "action": "ai_summarize",
                "params": {
                    "content": "context.transcript.text",
                    "instruction": "Extract a bullet-point task list for tomorrow based on this transcript.",
                },
                "output_key": "tasks",
            },
            {
                "app": "innate",
                "action": "get_datetime",
                "params": {"format": "MMM d"},
                "output_key": "tomorrow_date",
            },
            {
                "app": "notion",
                "action": "create_page",
                "params": {"title": "Tasks — context.tomorrow_date", "content": "context.tasks"},
            },
        ],
    },
]


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"Seeding 3 workflows for {USER} → {BASE}")
        resp = await client.post(
            f"{BASE}/workflow/seed",
            json={"user_id": USER, "workflows": WORKFLOWS},
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data["seeded"]:
                print(f"  ✓  {item['trigger_phrase']!r}  (id={item['id']})")
        else:
            print(f"  ✗  HTTP {resp.status_code}: {resp.text[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
