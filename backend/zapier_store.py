"""
zapier_store.py
MongoDB CRUD for Zapier webhook URLs.

Each document maps (user_id, app, action) → webhook_url.
{
    user_id:     str
    app:         str   # "gmail" | "google_calendar" | "slack"
    action:      str   # "send_email" | "create_event" | "send_dm" | ...
    webhook_url: str   # https://hooks.zapier.com/hooks/catch/...
    label:       str   # optional human-readable label
    created_at:  datetime
    updated_at:  datetime
}
"""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo import ReturnDocument

from db import db

_col = db["zapier_webhooks"]


async def save_webhook(
    user_id: str,
    app: str,
    action: str,
    webhook_url: str,
    label: str = "",
) -> str:
    """Upsert a webhook URL for (user_id, app, action). Returns the document _id."""
    now = datetime.now(timezone.utc)
    result = await _col.find_one_and_update(
        {"user_id": user_id, "app": app, "action": action},
        {
            "$set": {"webhook_url": webhook_url, "label": label, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(result["_id"])


async def get_webhook_url(user_id: str, app: str, action: str) -> str | None:
    """Return the webhook URL for (user_id, app, action), or None if not configured."""
    doc = await _col.find_one({"user_id": user_id, "app": app, "action": action})
    return doc["webhook_url"] if doc else None


async def list_webhooks(user_id: str) -> list[dict]:
    """All webhooks for a user, sorted by app then action."""
    cursor = _col.find({"user_id": user_id}, sort=[("app", 1), ("action", 1)])
    docs = await cursor.to_list(length=200)
    for d in docs:
        d["_id"] = str(d["_id"])
        for key in ("created_at", "updated_at"):
            if key in d:
                d[key] = d[key].isoformat()
    return docs


async def delete_webhook(user_id: str, app: str, action: str) -> bool:
    result = await _col.delete_one({"user_id": user_id, "app": app, "action": action})
    return result.deleted_count > 0
