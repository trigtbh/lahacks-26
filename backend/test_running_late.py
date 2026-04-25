"""
test_running_late.py
End-to-end test for the "I'm running late" workflow.

Run with the server already started:
    # terminal 1
    cd backend && uvicorn main:app --reload

    # terminal 2
    cd backend && python test_running_late.py

Step 1  — saves the workflow to MongoDB
Step 2  — fires it by trigger phrase, executes Gmail + GCal
"""

import json
import requests

BASE  = "http://localhost:8000"
USER  = "test_user"

RUNNING_LATE_WORKFLOW = {
    "user_id":        USER,
    "trigger_phrase": "I'm running late",
    "steps": [
        {
            "app":    "gmail",
            "action": "send_email",
            "params": {
                "to":      "calendar.next_event.attendees",
                "subject": "Running late",
                "body":    "Hey, I'm running about 15 minutes late for our meeting. Pushing the invite too — sorry!",
            },
        },
        {
            "app":    "google_calendar",
            "action": "push_event",
            "params": {
                "event_ref":  "calendar.next_event",
                "by_minutes": 15,
            },
        },
    ],
}


def pp(label: str, data: dict) -> None:
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    print(json.dumps(data, indent=2, default=str))


def test_create() -> str:
    resp = requests.post(f"{BASE}/workflow/create", json=RUNNING_LATE_WORKFLOW)
    resp.raise_for_status()
    data = resp.json()
    pp("POST /workflow/create", data)
    assert data.get("status") == "saved", f"unexpected status: {data}"
    return data["workflow_id"]


def test_list() -> None:
    resp = requests.get(f"{BASE}/workflow/list/{USER}")
    resp.raise_for_status()
    data = resp.json()
    pp(f"GET /workflow/list/{USER}", data)


def test_trigger() -> None:
    resp = requests.post(f"{BASE}/workflow/trigger", json={
        "user_id":        USER,
        "trigger_phrase": "I'm running late",
    })
    resp.raise_for_status()
    data = resp.json()
    # strip audio bytes from print (too long)
    display = {k: v for k, v in data.items() if k != "audio_b64"}
    if data.get("audio_b64"):
        display["audio_b64"] = f"<{len(data['audio_b64'])} chars>"
    pp("POST /workflow/trigger", display)
    assert data.get("status") in ("success", "partial"), \
        f"execution failed: {data}"


if __name__ == "__main__":
    print("Step 1 — create workflow")
    workflow_id = test_create()

    print("\nStep 2 — list workflows (verify saved)")
    test_list()

    print("\nStep 3 — trigger workflow (runs Gmail + GCal)")
    test_trigger()

    print("\n\nAll steps done.")
