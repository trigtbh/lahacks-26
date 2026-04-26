"""
tests/test_workflows.py
End-to-end integration test for the three canonical Flux demo workflows.

Each test fires a trigger phrase at the live backend and asserts that the
real integrations (Google Calendar, Gmail, Slack, Notion) complete successfully.
Workflows must already be saved in MongoDB for the user before running.

Usage:
    cd backend
    python tests/test_workflows.py

    # Against the deployed server:
    BASE=https://flux.trigtbh.dev USER=justin python tests/test_workflows.py
"""

import asyncio
import os
import sys

import httpx

BASE = os.getenv("BASE", "http://localhost:8000")
USER = os.getenv("USER", "ved29022004@gmail.com")

# ── ANSI colours ─────────────────────────────────────────
GRN  = "\033[92m"
RED  = "\033[91m"
YLW  = "\033[93m"
BLU  = "\033[94m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"


# ── Three canonical workflows ─────────────────────────────
WORKFLOWS = [
    {
        "name":       "Running Late",
        "transcript": "I'm running late by 15 minutes",
        "expect":     ["google_calendar.push_event", "gmail.send_email"],
    },
    {
        "name":       "Morning Brief",
        "transcript": "morning brief",
        "expect":     ["gmail.search_email", "innate.ai_summarize"],
    },
    {
        "name":       "End of Day",
        "transcript": "I'm done with the day",
        "expect":     ["google_drive.read_document", "slack.send_channel", "notion.create_page"],
    },
]


# ── Helpers ───────────────────────────────────────────────
def _hdr(text: str) -> None:
    print(f"\n{BOLD}{BLU}{'─' * 62}{RST}")
    print(f"{BOLD}{BLU}  {text}{RST}")
    print(f"{BOLD}{BLU}{'─' * 62}{RST}")


def _ok(msg: str)   -> None: print(f"  {GRN}✓{RST}  {msg}")
def _fail(msg: str) -> None: print(f"  {RED}✗{RST}  {msg}")
def _info(msg: str) -> None: print(f"  {DIM}·{RST}  {msg}")


def _result_snippet(result) -> str:
    if isinstance(result, list):
        return f"→ {len(result)} item(s)"
    if isinstance(result, dict):
        keys = list(result.keys())[:3]
        return f"→ {{{', '.join(keys)}}}"
    if isinstance(result, str) and result:
        return f"→ {result[:70]}"
    return ""


# ── Per-workflow test ─────────────────────────────────────
async def run_one(client: httpx.AsyncClient, wf: dict) -> bool:
    _hdr(wf["name"])
    print(f"  Trigger : {YLW}{wf['transcript']!r}{RST}")

    try:
        resp = await client.post(
            f"{BASE}/workflow/trigger",
            json={"user_id": USER, "trigger_phrase": wf["transcript"]},
        )
    except httpx.RequestError as exc:
        _fail(f"Request error: {exc}")
        return False

    if resp.status_code != 200:
        _fail(f"HTTP {resp.status_code} — {resp.text[:200]}")
        return False

    data = resp.json()
    status = data.get("status", "")

    if status == "no_match":
        _fail("No matching workflow in MongoDB — create it first with the app.")
        return False

    if status == "token_expired":
        _fail("Google token expired — re-auth at: " + data.get("reauth_url", "(no URL)"))
        return False

    matched = data.get("trigger_matched", "?")
    print(f"  Matched : {GRN}{matched!r}{RST}")
    print()

    completed = data.get("steps_completed", [])
    failed    = data.get("steps_failed",    [])

    for step in completed:
        label   = step.get("step", "?")
        snippet = _result_snippet(step.get("result"))
        _ok(f"{BOLD}{label}{RST}  {DIM}{snippet}{RST}")

    for step in failed:
        _fail(f"{BOLD}{step.get('step', '?')}{RST}  {step.get('error', '?')}")

    # Check expected steps ran
    completed_labels = {s.get("step", "") for s in completed}
    missing = [e for e in wf["expect"] if e not in completed_labels]
    for m in missing:
        _info(f"expected step not found: {m}")

    passed = status in ("success", "partial") and len(completed) > 0 and not missing
    verdict = f"{GRN}{BOLD}PASS{RST}" if passed else f"{RED}{BOLD}FAIL{RST}"
    print(f"\n  {verdict}  —  {len(completed)} completed, {len(failed)} failed")
    return passed


# ── Startup check ─────────────────────────────────────────
async def check_server(client: httpx.AsyncClient) -> bool:
    _hdr("Server + Saved Workflows")
    print(f"  {DIM}BASE : {BASE}{RST}")
    print(f"  {DIM}USER : {USER}{RST}\n")
    try:
        r = await client.get(f"{BASE}/workflow/list/{USER}")
        r.raise_for_status()
    except Exception as exc:
        _fail(f"Cannot reach server: {exc}")
        return False

    body = r.json()
    workflows = body.get("workflows", body) if isinstance(body, dict) else body
    _ok(f"Server reachable — {len(workflows)} workflow(s) saved for '{USER}'")
    for w in workflows:
        _info(w.get("trigger_phrase", "(no trigger)"))
    return True


# ── Main ──────────────────────────────────────────────────
async def main() -> None:
    print(f"\n{BOLD}Flux — Integration Test Suite{RST}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        if not await check_server(client):
            sys.exit(1)

        results: list[tuple[str, bool]] = []
        for wf in WORKFLOWS:
            passed = await run_one(client, wf)
            results.append((wf["name"], passed))

    # ── Summary ───────────────────────────────────────────
    print(f"\n{BOLD}{'═' * 62}{RST}")
    print(f"{BOLD}  Summary{RST}")
    print(f"{BOLD}{'═' * 62}{RST}")
    all_passed = True
    for name, passed in results:
        icon = f"{GRN}PASS{RST}" if passed else f"{RED}FAIL{RST}"
        print(f"  {icon}  {name}")
        if not passed:
            all_passed = False
    print()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
