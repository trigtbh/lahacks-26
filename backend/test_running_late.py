"""
test_running_late.py
End-to-end test for the "I'm running late" workflow.

Prerequisites:
  - Server running:  cd backend && uvicorn main:app --reload
  - backend/.env has: GEMINI_API_KEY, MONGO_URL
  - backend/ has:     token.pickle + credentials.json  (Google OAuth)

Flow:
  Step 1 — POST /workflow/create
           transcript: "When I say I'm running late, shift my next meeting by 10 mins
                        and email the attendees"
           → classifier extracts trigger + steps → saved to MongoDB

  Step 2 — POST /workflow/trigger
           trigger_phrase: "I'm running late"
           → MongoDB lookup → executor runs Gmail + GCal → done
"""

import json
import requests

BASE = "http://localhost:8000"
USER = "test_user"


def pp(label: str, data: dict) -> None:
    print(f"\n{'=' * 55}")
    print(f"  {label}")
    print(f"{'=' * 55}")
    # strip audio bytes — too long to print
    display = {k: (f"<{len(v)} chars>" if k == "audio_b64" and v else v)
               for k, v in data.items()}
    print(json.dumps(display, indent=2, default=str))


# ─────────────────────────────────────────────
# Step 1 — create workflow from natural language
# ─────────────────────────────────────────────
def test_create() -> dict:
    transcript = (
        "When I say I'm running late, "
        "shift my next meeting by 10 mins and email the attendees"
    )
    print(f"\nTranscript: {transcript!r}")

    resp = requests.post(f"{BASE}/workflow/create", json={
        "user_id":    USER,
        "transcript": transcript,
    })
    resp.raise_for_status()
    data = resp.json()
    pp("POST /workflow/create  (AI classified + saved)", data)

    assert data.get("trigger_phrase"), "No trigger_phrase in response"
    assert data.get("steps"),          "No steps in response"
    print(f"\n  trigger_phrase : {data['trigger_phrase']!r}")
    print(f"  steps ({len(data['steps'])})     :", [f"{s['app']}.{s['action']}" for s in data['steps']])
    if data.get("validation_errors"):
        print(f"  validation     : {data['validation_errors']}")
    return data


# ─────────────────────────────────────────────
# Verify it's in Mongo
# ─────────────────────────────────────────────
def test_list() -> None:
    resp = requests.get(f"{BASE}/workflow/list/{USER}")
    resp.raise_for_status()
    data = resp.json()
    pp(f"GET /workflow/list/{USER}  (verify saved)", data)


# ─────────────────────────────────────────────
# Step 2 — fire the trigger → execute Gmail + GCal
# ─────────────────────────────────────────────
def test_trigger() -> None:
    spoken = "I'm running late"
    print(f"\nSpoken: {spoken!r}")

    resp = requests.post(f"{BASE}/workflow/trigger", json={
        "user_id":        USER,
        "trigger_phrase": spoken,
    })
    resp.raise_for_status()
    data = resp.json()
    pp("POST /workflow/trigger  (execute)", data)

    assert data.get("status") != "no_match",  "No matching workflow found in MongoDB"
    assert data.get("status") in ("success", "partial"), f"Execution failed: {data}"
    print(f"\n  matched trigger : {data.get('trigger_matched')!r}")
    print(f"  event affected  : {data.get('event_title')!r}")
    print(f"  completed       : {[s['step'] for s in data.get('steps_completed', [])]}")
    if data.get("steps_failed"):
        print(f"  FAILED          : {data['steps_failed']}")


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("STEP 1 — Classify transcript + save to MongoDB")
    test_create()

    print("\nSTEP 2 — Verify it's in MongoDB")
    test_list()

    print("\nSTEP 3 — Fire trigger -> execute Gmail + GCal")
    test_trigger()

    print("\n\nAll done.")
