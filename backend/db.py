"""
db.py
Shared async MongoDB client (Motor).
Import `db` anywhere in the backend — Motor connects lazily.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGO_DB",  "lahacks")

_client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db = _client[DB_NAME]
