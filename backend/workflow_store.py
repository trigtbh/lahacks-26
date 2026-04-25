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

All functions no-op gracefully when MONGO_ENABLED is false.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import Any

from ai.llm import generate_json
from ai.prompts import TRIGGER_SYSTEM, build_trigger_match_prompt
from db import db, MONGO_ENABLED

_col = db["workflows"] if db is not None else None


_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_trigger_text(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("i'm", "i am")
    text = text.replace("im", "i am")
    text = text.replace("you're", "you are")
    text = text.replace("we're", "we are")
    text = text.replace("they're", "they are")
    text = text.replace("can't", "cannot")
    text = text.replace("won't", "will not")
    text = text.replace("n't", " not")
    text = text.replace("'re", " are")
    text = text.replace("'ll", " will")
    text = text.replace("'ve", " have")
    text = text.replace("'d", " would")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


async def _semantic_match_trigger(
    spoken: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not candidates:
        return None

    saved_triggers = [
        candidate.get("trigger_phrase", "").strip()
        for candidate in candidates
        if candidate.get("trigger_phrase", "").strip()
    ]
    if not saved_triggers:
        return None

    try:
        result = await asyncio.to_thread(
            generate_json,
            TRIGGER_SYSTEM,
            build_trigger_match_prompt(spoken, saved_triggers),
            0.0,
        )
    except Exception:
        return None

    if not result.get("matched"):
        return None

    matched_trigger = str(result.get("trigger_phrase") or "").strip()
    if not matched_trigger:
        return None

    normalized_match = _normalize_trigger_text(matched_trigger)
    for candidate in candidates:
        stored = candidate.get("trigger_phrase", "").strip()
        if not stored:
            continue
        if stored.lower() == matched_trigger.lower():
            return candidate
        if _normalize_trigger_text(stored) == normalized_match:
            return candidate

    return None


async def save_workflow(
    user_id: str,
    trigger_phrase: str,
    steps: list[dict[str, Any]],
) -> str:
    """Persist a workflow. Returns the new document _id as a string."""
    if not MONGO_ENABLED or _col is None:
        return ""
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
    if not MONGO_ENABLED or _col is None:
        return []
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
    if not MONGO_ENABLED or _col is None:
        return None
    spoken_stripped = spoken.strip()
    normalized_spoken = _normalize_trigger_text(spoken_stripped)

    # 1. Exact
    doc = await _col.find_one({
        "user_id": user_id,
        "trigger_phrase": {"$regex": f"^{spoken_stripped}$", "$options": "i"},
    })
    if doc:
        return doc

    # 2. Normalized / substring matching
    candidates = await _col.find({"user_id": user_id}).to_list(length=200)
    for candidate in candidates:
        stored = candidate.get("trigger_phrase", "")
        normalized_stored = _normalize_trigger_text(stored)
        if stored.lower() in spoken_stripped.lower():
            return candidate
        if normalized_stored and (
            normalized_stored == normalized_spoken
            or normalized_stored in normalized_spoken
            or normalized_spoken in normalized_stored
        ):
            return candidate

    # 3. Semantic similarity fallback via the existing trigger-matching prompt.
    return await _semantic_match_trigger(spoken_stripped, candidates)


async def delete_workflow(workflow_id: str) -> bool:
    """Delete by _id string. Returns True if a document was deleted."""
    if not MONGO_ENABLED or _col is None:
        return False
    try:
        from bson import ObjectId
        result = await _col.delete_one({"_id": ObjectId(workflow_id)})
        return result.deleted_count > 0
    except Exception:
        return False
