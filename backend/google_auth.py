"""
google_auth.py
Shared Google OAuth credential loading for all Google API clients.
"""

from __future__ import annotations

import os

import google.auth.transport.requests
import google.oauth2.credentials

import token_store


async def get_google_creds(user_id: str) -> google.oauth2.credentials.Credentials:
    doc = await token_store.get_token(user_id, "google")
    if not doc:
        raise ValueError(f"No Google OAuth token for user '{user_id}' — connect via /auth/google")

    creds = google.oauth2.credentials.Credentials(
        token=doc["access_token"],
        refresh_token=doc.get("refresh_token"),
        token_uri=doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=doc.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        await token_store.save_token(user_id, "google", {
            "access_token":  creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "scopes":        list(creds.scopes or []),
        })

    return creds
