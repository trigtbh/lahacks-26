"""
google_people.py
Google People API helpers for contact lookup by name.
"""

from __future__ import annotations

import logging

from googleapiclient.discovery import build

from google_auth import get_google_creds

log = logging.getLogger(__name__)


async def search_contacts(user_id: str, name: str) -> list[dict]:
    """
    Search the user's contacts by name via People API searchContacts.
    Returns a list of {name, email, phone} dicts ordered by relevance.
    """
    creds = await get_google_creds(user_id)
    service = build("people", "v1", credentials=creds)

    result = service.people().searchContacts(
        query=name,
        readMask="names,emailAddresses,phoneNumbers",
        pageSize=5,
    ).execute()

    contacts = []
    for item in result.get("results", []):
        person = item.get("person", {})
        display_name = (person.get("names") or [{}])[0].get("displayName", "")
        email = (person.get("emailAddresses") or [{}])[0].get("value", "")
        phone = (person.get("phoneNumbers") or [{}])[0].get("value", "")
        contacts.append({"name": display_name, "email": email, "phone": phone})

    log.info("People search %r → %d result(s)", name, len(contacts))
    return contacts


async def resolve_contact_email(user_id: str, name: str) -> str:
    contacts = await search_contacts(user_id, name)
    for c in contacts:
        if c["email"]:
            return c["email"]
    raise ValueError(f"No email found in contacts for '{name}'")


async def resolve_contact_phone(user_id: str, name: str) -> str:
    contacts = await search_contacts(user_id, name)
    for c in contacts:
        if c["phone"]:
            return c["phone"]
    raise ValueError(f"No phone number found in contacts for '{name}'")
