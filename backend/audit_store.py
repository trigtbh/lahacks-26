"""Mongo-backed audit trail for workflow preview, confirmation, and execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import db, MONGO_ENABLED

_col = db["workflow_audit"] if db is not None else None


def _normalize_user_id(user_id: str) -> str:
    return user_id.strip().lower()


async def create_audit_record(
    user_id: str,
    record: dict[str, Any],
) -> str:
    if not MONGO_ENABLED or _col is None:
        return ""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": _normalize_user_id(user_id),
        "created_at": now,
        "updated_at": now,
        **record,
    }
    result = await _col.insert_one(payload)
    return str(result.inserted_id)


async def update_audit_record(audit_id: str, updates: dict[str, Any]) -> None:
    if not MONGO_ENABLED or _col is None or not audit_id:
        return
    try:
        from bson import ObjectId

        await _col.find_one_and_update(
            {"_id": ObjectId(audit_id)},
            {"$set": {**updates, "updated_at": datetime.now(timezone.utc)}},
        )
    except Exception:
        return


async def list_audit_records(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not MONGO_ENABLED or _col is None:
        return []
    cursor = _col.find(
        {"user_id": _normalize_user_id(user_id)},
        sort=[("created_at", -1)],
    )
    docs = await cursor.to_list(length=limit)
    for doc in docs:
        doc["_id"] = str(doc["_id"])
        for key in ("created_at", "updated_at"):
            if key in doc and hasattr(doc[key], "isoformat"):
                doc[key] = doc[key].isoformat()
    return docs
