"""
app_resolver.py
Derives the set of app names a specific user can use, based on their
connected OAuth services and registered Zapier webhooks.
"""

from __future__ import annotations

import os

import token_store
import zapier_store

_GOOGLE_APPS = {"gmail", "google_calendar", "google_drive"}


async def get_available_apps(user_id: str) -> set[str]:
    """
    Return the set of ALLOWED_ACTIONS app names available to this user.

    INNATE_ACTIONS and CONTROL_ACTIONS are always available — callers should
    include "innate" and "control" unconditionally (build_system_prompt does this).
    """
    available: set[str] = set()

    # OAuth-backed services
    connections = await token_store.list_connections(user_id)
    for service in connections:
        if service == "google":
            available.update(_GOOGLE_APPS)
        elif service == "slack":
            available.add("slack")

    # Server-side API key services (available to all users if keys are configured)
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        available.add("google_maps")
    if os.environ.get("SERPAPI_KEY"):
        available.add("google_flights")

    # Zapier-webhook-backed services
    webhooks = await zapier_store.list_webhooks(user_id)
    for wh in webhooks:
        app = wh.get("app", "")
        if app:
            available.add(app)

    # Credential-backed services
    if "dominos" in connections:
        available.add("dominos")

    return available
