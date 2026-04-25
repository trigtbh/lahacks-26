"""
executor.py
Executes workflow steps by POSTing resolved params to Zapier webhook URLs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

import zapier_store

log = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds per webhook call


# ─────────────────────────────────────────────
# Param resolver
# ─────────────────────────────────────────────

def _resolve(value: Any) -> Any:
    """Swap resolver strings for concrete values at execution time."""
    if not isinstance(value, str):
        return value
    if value == "time.now":
        return datetime.now(timezone.utc).isoformat()
    if value.startswith("time.now+") and value.endswith("m"):
        try:
            minutes = int(value[len("time.now+"):-1])
            return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        except ValueError:
            pass
    # All other resolver strings are passed through as literal values —
    # the Zapier workflow on the other end handles dynamic resolution.
    return value


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def execute_workflow(user_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Resolve params and POST each step to its configured Zapier webhook.

    Returns:
        {
          status:          "success" | "partial" | "failed",
          steps_completed: [...],
          steps_failed:    [...],
        }
    """
    completed: list[dict] = []
    failed: list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for step in steps:
            app    = step.get("app", "")
            action = step.get("action", "")
            resolved = {k: _resolve(v) for k, v in step.get("params", {}).items()}

            webhook_url = await zapier_store.get_webhook_url(user_id, app, action)
            if not webhook_url:
                msg = f"No Zapier webhook configured for {app}.{action}"
                log.warning("user=%s %s", user_id, msg)
                failed.append({"step": f"{app}.{action}", "error": msg})
                continue

            try:
                resp = await client.post(webhook_url, json=resolved)
                resp.raise_for_status()
                completed.append({"step": f"{app}.{action}", "params": resolved})
                log.info("Fired %s.%s → HTTP %s", app, action, resp.status_code)
            except httpx.HTTPStatusError as exc:
                err = f"Webhook returned HTTP {exc.response.status_code}"
                log.error("%s.%s %s", app, action, err)
                failed.append({"step": f"{app}.{action}", "error": err})
            except Exception as exc:
                log.error("%s.%s failed: %s", app, action, exc, exc_info=True)
                failed.append({"step": f"{app}.{action}", "error": str(exc)})

    status = "success" if not failed else ("failed" if not completed else "partial")
    return {
        "status":          status,
        "steps_completed": completed,
        "steps_failed":    failed,
    }
