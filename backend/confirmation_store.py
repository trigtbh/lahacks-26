"""In-memory pending confirmations for workflow create/execute actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PendingConfirmation:
    user_id: str
    kind: str
    command_text: str
    transcript: str
    workflow_id: str = ""
    workflow_trigger: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    preview: dict[str, Any] = field(default_factory=dict)
    workflow_schema: dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_pending: dict[str, PendingConfirmation] = {}


def get_pending(user_id: str) -> PendingConfirmation | None:
    return _pending.get(user_id.strip().lower())


def set_pending(item: PendingConfirmation) -> PendingConfirmation:
    _pending[item.user_id.strip().lower()] = item
    return item


def pop_pending(user_id: str) -> PendingConfirmation | None:
    return _pending.pop(user_id.strip().lower(), None)


def clear_pending(user_id: str) -> None:
    _pending.pop(user_id.strip().lower(), None)
