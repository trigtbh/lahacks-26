"""
environment.py
The closed world for the workflow AI layer.
All allowed apps, actions, params, and resolvers live here.
Gemini is ONLY allowed to use what's defined in this file.
"""

from typing import Any

# ─────────────────────────────────────────────
# ALLOWED APPS + ACTIONS
# Each action has: required_params, optional_params, description
# ─────────────────────────────────────────────

ALLOWED_ACTIONS: dict[str, dict] = {

    "gmail": {
        "send_email": {
            "required": ["to", "subject", "body"],
            "optional": ["cc"],
            "description": "Send an email immediately",
        },
        "draft_email": {
            "required": ["to", "subject", "body"],
            "optional": ["cc"],
            "description": "Save a draft without sending",
        },
        "search_email": {
            "required": ["query"],
            "optional": ["max_results"],
            "description": "Search inbox and return matching emails",
        },
    },

    "slack": {
        "send_dm": {
            "required": ["to", "message"],
            "optional": [],
            "description": "Send a direct message to a Slack user",
        },
        "send_channel": {
            "required": ["channel", "message"],
            "optional": [],
            "description": "Post a message to a Slack channel",
        },
    },

    "google_calendar": {
        "create_event": {
            "required": ["title", "start_time", "end_time"],
            "optional": ["attendees", "location", "description"],
            "description": "Create a new calendar event",
        },
        "push_event": {
            "required": ["event_ref", "by_minutes"],
            "optional": [],
            "description": "Push an existing event forward by N minutes",
        },
        "cancel_event": {
            "required": ["event_ref"],
            "optional": [],
            "description": "Cancel a calendar event",
        },
    },

    "uber": {
        "request_ride": {
            "required": ["destination"],
            "optional": ["pickup"],
            "description": "Request an Uber ride. Pickup defaults to current location.",
        },
    },

    "spotify": {
        "play": {
            "required": [],
            "optional": ["query", "playlist", "artist", "genre"],
            "description": "Play music. Can be a song, artist, genre, or playlist.",
        },
        "pause": {
            "required": [],
            "optional": [],
            "description": "Pause current playback",
        },
        "skip": {
            "required": [],
            "optional": [],
            "description": "Skip to the next track",
        },
        "set_volume": {
            "required": ["level"],
            "optional": [],
            "description": "Set volume 0-100",
        },
    },

    "notion": {
        "create_page": {
            "required": ["title", "content"],
            "optional": ["database_id", "tags"],
            "description": "Create a new Notion page",
        },
        "append_to_page": {
            "required": ["page_ref", "content"],
            "optional": [],
            "description": "Append content to an existing Notion page",
        },
    },

    "github": {
        "create_issue": {
            "required": ["repo", "title"],
            "optional": ["body", "assignee", "labels"],
            "description": "Open a new GitHub issue",
        },
        "assign_issue": {
            "required": ["repo", "issue_number", "assignee"],
            "optional": [],
            "description": "Assign an existing issue to someone",
        },
        "comment_on_issue": {
            "required": ["repo", "issue_number", "comment"],
            "optional": [],
            "description": "Add a comment to a GitHub issue",
        },
    },

    "dominos": {
        "order_pizza": {
            "required": ["size", "toppings", "address"],
            "optional": ["crust", "quantity", "store_id"],
            "description": "Place a pizza order for delivery",
        },
        "reorder_last": {
            "required": [],
            "optional": ["address"],
            "description": "Reorder the user's most recent Domino's order",
        },
        "track_order": {
            "required": ["order_id"],
            "optional": [],
            "description": "Track the status of an existing order",
        },
    }
}


# ─────────────────────────────────────────────
# RESOLVERS
# Dynamic values evaluated at workflow execution time.
# Gemini should reference these keys instead of hardcoding values.
# Format: "resolver_key" -> human readable description
# ─────────────────────────────────────────────

RESOLVERS: dict[str, str] = {
    # Calendar
    "calendar.next_event.title":        "Title of the user's next calendar event",
    "calendar.next_event.attendees":    "List of attendees in the next calendar event",
    "calendar.next_event.start_time":   "Start time of the next calendar event",
    "calendar.next_event.location":     "Location of the next calendar event",
    "calendar.next_event": "Full next calendar event object",

    # Location
    "user.current_location":            "User's current GPS location (lat/lng)",
    "user.home_address":                "User's saved home address",
    "user.work_address":                "User's saved work address",

    # Contacts
    "user.contacts.by_name:{name}":     "Look up a contact's details by name. Replace {name} with the person's name.",
    "user.contacts.slack_handle:{name}":"Look up someone's Slack handle by name. Replace {name} with their name.",
    "user.contacts.email:{name}":       "Look up someone's email by name. Replace {name} with their name.",

    # Time
    "time.now":                         "Current timestamp",
    "time.now+{minutes}m":              "Current time plus N minutes. Replace {minutes} with a number.",

    # GitHub
    "github.repo.default":              "The user's default/primary GitHub repo",

    # Food / preferences
    "user.favorite_pizza": "User's saved favorite pizza configuration (size, toppings, crust)",
    "user.last_pizza_order": "Details of the user's most recent pizza order",

    # Location reuse (you already have some)
    "user.delivery_address": "User's default food delivery address",

    "uber.ride_link": "Generate Uber deep link for a ride",
}


# ─────────────────────────────────────────────
# WORKFLOW JSON SCHEMA
# What Gemini must return. Validated against this.
# ─────────────────────────────────────────────

WORKFLOW_SCHEMA = {
    "intent": str,                  # "create_workflow" | "trigger_workflow" | "other"
    "trigger_phrase": str,          # The phrase that activates this workflow
    "steps": list,                  # List of step objects (see STEP_SCHEMA)
    "missing_params": list,         # Params Gemini couldn't resolve
    "confidence": float,            # 0.0 - 1.0
}

STEP_SCHEMA = {
    "app": str,                     # Must be a key in ALLOWED_ACTIONS
    "action": str,                  # Must be a key in ALLOWED_ACTIONS[app]
    "params": dict,                 # key: value or key: resolver_string
    "unsupported": bool,            # True if Gemini flagged this step as unsupported
}


# ─────────────────────────────────────────────
# SYSTEM PROMPT FRAGMENT
# Injected into every Gemini call. Single source of truth.
# ─────────────────────────────────────────────

def build_system_prompt() -> str:
    apps_block = ""
    for app, actions in ALLOWED_ACTIONS.items():
        apps_block += f"\n  {app}:\n"
        for action, meta in actions.items():
            apps_block += f"    - {action}: required={meta['required']}, optional={meta['optional']}\n"

    resolvers_block = "\n".join(
        f"  {key}: {desc}" for key, desc in RESOLVERS.items()
    )

    return f"""You are a workflow parser for a voice-activated automation app.

RULES:
1. You MUST only use apps and actions from the ALLOWED list below. Never invent new ones.
2. For dynamic values, use ONLY resolver keys from the RESOLVERS list. Never hardcode names, emails, or phone numbers.
3. If a step requires an app not in the list, set "unsupported": true on that step and still include it.
4. Return ONLY valid JSON. No markdown, no explanation, no code fences.
5. If you cannot resolve a param, add it to missing_params as a plain English description.
6. Confidence should reflect how well you understood the user's intent (0.0-1.0).

ALLOWED APPS AND ACTIONS:
{apps_block}

RESOLVERS (use these keys for dynamic values):
{resolvers_block}

OUTPUT SCHEMA:
{{
  "intent": "create_workflow" | "trigger_workflow" | "other",
  "trigger_phrase": "<phrase that activates this workflow>",
  "steps": [
    {{
      "app": "<app name>",
      "action": "<action name>",
      "params": {{
        "<param_name>": "<static value or resolver key>"
      }},
      "unsupported": false
    }}
  ],
  "missing_params": ["<plain english description of what's missing>"],
  "confidence": 0.95
}}"""


# ─────────────────────────────────────────────
# HELPER UTILS
# ─────────────────────────────────────────────

def is_resolver(value: Any) -> bool:
    """Check if a param value is a resolver reference."""
    if not isinstance(value, str):
        return False
    # Resolvers are either exact keys or templated keys like user.contacts.by_name:{name}
    for key in RESOLVERS:
        template_base = key.split(":")[0]
        if value == key or value.startswith(template_base + ":"):
            return True
    return False


def get_allowed_apps() -> list[str]:
    return list(ALLOWED_ACTIONS.keys())


def get_allowed_actions(app: str) -> list[str]:
    return list(ALLOWED_ACTIONS.get(app, {}).keys())


def get_action_meta(app: str, action: str) -> dict | None:
    return ALLOWED_ACTIONS.get(app, {}).get(action)