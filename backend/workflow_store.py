"""
workflow_store.py
MongoDB CRUD for user workflows.

Schema (stored document):
{
    _id:            ObjectId   (auto)
    user_id:        str
    trigger_phrase: str        -- what the user says to fire this workflow
    steps:          list[dict] -- [{app, action, params}, ...]
    created_at:     datetime
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from db import db

_col = db["workflows"]


async def save_workflow(
    user_id: str,
    trigger_phrase: str,
    steps: list[dict[str, Any]],
) -> str:
    """Persist a workflow. Returns the new document _id as a string."""
    doc = {
        "user_id":        user_id,
        "trigger_phrase": trigger_phrase.strip(),
        "steps":          steps,
        "created_at":     datetime.now(timezone.utc),
    }
    result = await _col.insert_one(doc)
    return str(result.inserted_id)


async def list_workflows(user_id: str) -> list[dict[str, Any]]:
    """All workflows for a user, newest first."""
    cursor = _col.find({"user_id": user_id}, sort=[("created_at", -1)])
    docs = await cursor.to_list(length=200)
    for d in docs:
        d["_id"] = str(d["_id"])
        if "created_at" in d:
            d["created_at"] = d["created_at"].isoformat()
    return docs


async def find_by_trigger(user_id: str, spoken: str) -> dict[str, Any] | None:
    """
    Find the best matching workflow for a spoken phrase.
    Priority:
      1. Exact match (case-insensitive)
      2. Spoken phrase contains the stored trigger
      3. Stored trigger contains the spoken phrase
    """
    spoken_stripped = spoken.strip()

    # 1. Exact
    doc = await _col.find_one({
        "user_id": user_id,
        "trigger_phrase": {"$regex": f"^{spoken_stripped}$", "$options": "i"},
    })
    if doc:
        return doc

    # 2. Stored trigger is a substring of what was spoken
    cursor = _col.find({"user_id": user_id})
    async for candidate in cursor:
        stored = candidate.get("trigger_phrase", "")
        if stored.lower() in spoken_stripped.lower():
            return candidate

    return None


async def delete_workflow(workflow_id: str) -> bool:
    """Delete by _id string. Returns True if a document was deleted."""
    try:
        result = await _col.delete_one({"_id": ObjectId(workflow_id)})
        return result.deleted_count > 0
    except Exception:
        return False
