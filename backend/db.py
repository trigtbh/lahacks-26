"""
db.py
Shared async MongoDB client (Motor).
Import `db` anywhere in the backend — Motor connects lazily.

Set MONGO_ENABLED=true in .env (or environment) to enable persistence.
Defaults to False so the app runs without a MongoDB instance.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MONGO_ENABLED = True
MONGO_URL = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGO_DB",  "flow_db")

print(MONGO_URL, DB_NAME)

if MONGO_ENABLED:
    from motor.motor_asyncio import AsyncIOMotorClient
    _client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
    db = _client[DB_NAME]
else:
    db = None
