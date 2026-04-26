"""
tests/local_server.py
Fully local backend — zero MongoDB, zero Vultr dependency.
Tokens persist to tests/tokens.json so you only re-auth once.

FIRST-TIME SETUP (one-time only):
  1. In Google Cloud Console → APIs & Services → Credentials → your OAuth client
     → add  http://localhost:8000/connect/google/redirect  to Authorized redirect URIs
  2. Start this server:  python tests/local_server.py
  3. Visit in browser:   http://localhost:8000/auth/google?user_id=ved29022004@gmail.com
  4. Do the same for Slack / Notion if needed
  5. Tokens are saved to tests/tokens.json — step 3-4 never needed again

RUNNING THE TEST:
  python tests/test_workflows.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
TESTS_DIR  = Path(__file__).parent
BACKEND_DIR = TESTS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

TOKENS_FILE = TESTS_DIR / "tokens.json"

# ── Force local URLs before main.py reads env ─────────────────────────────────
os.environ["BACKEND_URL"]          = "http://localhost:8000"
os.environ["GOOGLE_REDIRECT_URI"]  = "http://localhost:8000/connect/google/redirect"

# ── In-memory token store backed by a local JSON file ────────────────────────
def _load_tokens() -> dict:
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_tokens(data: dict) -> None:
    TOKENS_FILE.write_text(json.dumps(data, indent=2))

_TOKENS: dict[str, dict] = _load_tokens()

import token_store

async def _get_token(user_id: str, service: str) -> dict | None:
    return _TOKENS.get(f"{user_id.strip().lower()}:{service}")

async def _save_token(user_id: str, service: str, token_data: dict) -> None:
    key = f"{user_id.strip().lower()}:{service}"
    existing = _TOKENS.get(key, {})
    existing.update(token_data)
    _TOKENS[key] = existing
    _save_tokens(_TOKENS)
    print(f"  [local] token saved: {key}")

async def _list_connections(user_id: str) -> list[str]:
    prefix = f"{user_id.strip().lower()}:"
    return [k[len(prefix):] for k in _TOKENS if k.startswith(prefix)]

async def _delete_token(user_id: str, service: str) -> bool:
    key = f"{user_id.strip().lower()}:{service}"
    existed = key in _TOKENS
    _TOKENS.pop(key, None)
    _save_tokens(_TOKENS)
    return existed

token_store.get_token       = _get_token
token_store.save_token      = _save_token
token_store.list_connections = _list_connections
token_store.delete_token    = _delete_token

# ── In-memory workflow store ───────────────────────────────────────────────────
import re as _re
_PUNCT = _re.compile(r"[^\w\s]")

def _norm(t: str) -> str:
    t = t.strip().lower()
    for a, b in [("i'm", "i am"), ("im ", "i am "), ("won't", "will not"), ("can't", "cannot")]:
        t = t.replace(a, b)
    return " ".join(_PUNCT.sub(" ", t).split())

WORKFLOWS: list[dict] = [
    {
        "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
        "user_id": "ved29022004@gmail.com",
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
                    "body": "Hey, running about 15 minutes late to our meeting. Sorry!",
                },
            },
        ],
        "created_at": "2026-01-01T00:00:00+00:00",
    },
    {
        "_id": "bbbbbbbbbbbbbbbbbbbbbbbb",
        "user_id": "ved29022004@gmail.com",
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
        "created_at": "2026-01-01T00:00:00+00:00",
    },
    {
        "_id": "cccccccccccccccccccccccc",
        "user_id": "ved29022004@gmail.com",
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
        "created_at": "2026-01-01T00:00:00+00:00",
    },
]

import workflow_store

async def _list_workflows(user_id: str) -> list[dict]:
    return [w for w in WORKFLOWS if w["user_id"] == user_id]

async def _find_by_trigger(user_id: str, spoken: str) -> dict | None:
    spoken_n = _norm(spoken)
    for wf in WORKFLOWS:
        if wf["user_id"] != user_id:
            continue
        stored_n = _norm(wf["trigger_phrase"])
        if spoken_n == stored_n or stored_n in spoken_n or spoken_n in stored_n:
            return wf
    return None

async def _save_workflow(user_id: str, trigger_phrase: str, steps: list[dict]) -> str:
    return "local-mock-id"

workflow_store.list_workflows  = _list_workflows
workflow_store.find_by_trigger = _find_by_trigger
workflow_store.save_workflow   = _save_workflow

# ── No-op audit store and zapier store (MongoDB-backed, not needed locally) ───
import audit_store
audit_store._col = None

import zapier_store
async def _list_webhooks(user_id: str) -> list: return []
async def _get_webhook(user_id: str, app: str, action: str): return None
zapier_store.list_webhooks = _list_webhooks
zapier_store.get_webhook   = _get_webhook

# ── Import main AFTER all patches so it picks them up ─────────────────────────
import main as _main

# Patch main's local reference to token_store functions (imported via module)
# main uses token_store.* via the module, so module-level patches above suffice.

# ── Start server ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    existing = [w["trigger_phrase"] for w in WORKFLOWS]
    print("\n[local] Workflows loaded:")
    for t in existing:
        print(f"  · {t!r}")
    tokens = list(_TOKENS.keys())
    if tokens:
        print(f"\n[local] Tokens on disk: {tokens}")
    else:
        print("\n[local] No tokens yet — visit http://localhost:8000/auth/google?user_id=ved29022004@gmail.com")
    print()

    import uvicorn
    uvicorn.run(_main.app, host="0.0.0.0", port=8000)
