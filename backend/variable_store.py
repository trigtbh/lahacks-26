"""
variable_store.py
MongoDB CRUD for global user variables.
"""

from datetime import datetime, timezone
from typing import Any

from db import db, MONGO_ENABLED

_col = db["variables"] if db is not None else None


async def set_global_variable(user_id: str, key: str, value: Any) -> None:
    if not MONGO_ENABLED or _col is None:
        return
    
    doc = {
        "user_id": user_id,
        "key": key,
        "value": value,
        "updated_at": datetime.now(timezone.utc),
    }
    
    await _col.update_one(
        {"user_id": user_id, "key": key},
        {"$set": doc},
        upsert=True
    )


async def get_global_variable(user_id: str, key: str, default: Any = None) -> Any:
    if not MONGO_ENABLED or _col is None:
        return default
        
    doc = await _col.find_one({"user_id": user_id, "key": key})
    if doc and "value" in doc:
        return doc["value"]
    return default
