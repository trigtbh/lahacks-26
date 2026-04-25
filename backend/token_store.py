"""
token_store.py
MongoDB storage for OAuth tokens per (user_id, service).
"""

from __future__ import annotations

from datetime import datetime, timezone

from db import db

_col = db["oauth_tokens"]


async def save_token(user_id: str, service: str, token_data: dict) -> None:
    """Upsert token data for (user_id, service)."""
    now = datetime.now(timezone.utc)
    await _col.find_one_and_update(
        {"user_id": user_id, "service": service},
        {
            "$set": {**token_data, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def get_token(user_id: str, service: str) -> dict | None:
    """Retrieve token data for (user_id, service), or None if not connected."""
    doc = await _col.find_one({"user_id": user_id, "service": service})
    if doc:
        doc.pop("_id", None)
    return doc


async def list_connections(user_id: str) -> list[str]:
    """Return list of services the user has connected."""
    cursor = _col.find({"user_id": user_id}, {"service": 1})
    docs = await cursor.to_list(length=50)
    return [d["service"] for d in docs]


async def delete_token(user_id: str, service: str) -> bool:
    result = await _col.delete_one({"user_id": user_id, "service": service})
    return result.deleted_count > 0
