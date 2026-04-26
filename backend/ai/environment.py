"""
environment.py
The closed world for the workflow AI layer.
All allowed apps, actions, params, and resolvers live here.
Gemini is ONLY allowed to use what's defined in this file.
"""

from __future__ import annotations
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
        "get_channels": {
            "required": [],
            "optional": ["limit"],
            "description": "Get a list of all available public channels in the Slack workspace",
        },
    },

    "google_people": {
        "list_contacts": {
            "required": [],
            "optional": ["limit"],
            "description": "List the user's contacts (connections). Read-only.",
        },
        "search_contacts": {
            "required": ["query"],
            "optional": ["limit"],
            "description": "Search for a specific contact by name or email. Read-only.",
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
        "get_page_link": {
            "required": ["page_ref"],
            "optional": [],
            "description": "Get the URL link to a Notion page",
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
    },

    "google_maps": {
        "get_directions": {
            "required": ["destination"],
            "optional": ["origin", "mode"],
            "description": "Get directions to a destination. origin defaults to current location. mode: driving, walking, transit, bicycling.",
        },
        "search_nearby": {
            "required": ["query"],
            "optional": ["location", "radius"],
            "description": "Search for nearby places by type or keyword (e.g. 'coffee', 'gas station').",
        },
    },

    "google_flights": {
        "search_flights": {
            "required": ["origin", "destination"],
            "optional": ["departure_date", "return_date", "num_adults", "cabin_class"],
            "description": "Search Google Flights for available flights. origin/destination are airport codes or city names. cabin_class: economy, premium_economy, business, first.",
        },
    },

    "google_drive": {
        "create_document": {
            "required": ["title"],
            "optional": ["content"],
            "description": "Create a new Google Doc with a title and optional text content.",
        },
        "search_files": {
            "required": ["query"],
            "optional": ["max_results"],
            "description": "Search Google Drive for files matching a name or keyword.",
        },
        "share_file": {
            "required": ["file_name", "email"],
            "optional": ["role"],
            "description": "Share a Drive file with someone by email. role: reader (default), writer, commenter.",
        },
    },

}


# ─────────────────────────────────────────────
# INNATE ACTIONS
# Run locally — no OAuth, no external API required.
# ─────────────────────────────────────────────

INNATE_ACTIONS: dict[str, dict] = {
    "get_datetime": {
        "required": [],
        "optional": ["format", "timezone"],
        "description": "Get current date/time. format: iso (default), human, date_only, time_only.",
    },
    "datetime_math": {
        "required": ["base_time", "operation", "amount", "unit"],
        "optional": ["format"],
        "description": "Perform datetime math (e.g. addition, subtraction). base_time: ISO string. operation: 'add' or 'subtract'. unit: 'days', 'hours', 'minutes', etc. Always provide an output_key.",
    },
    "set_variable": {
        "required": ["key", "value"],
        "optional": ["scope"],
        "description": "Store a value under the given key. scope: 'local' (this run only, default) or 'global' (persists across runs for this user).",
    },
    "get_variable": {
        "required": ["key"],
        "optional": ["default"],
        "description": "Read a value by key. Checks local context first, then global variables. Returns default if missing.",
    },
    "calculate": {
        "required": ["expression"],
        "optional": [],
        "description": "Evaluate a safe numeric expression. Use {{context.key}} to reference context values. You MUST provide an 'output_key' on this step to save the calculated result.",
    },
    "format_text": {
        "required": ["template"],
        "optional": [],
        "description": "Render a template string. Use {{context.key}} to interpolate context values.",
    },
    "join_list": {
        "required": ["items"],
        "optional": ["separator", "final_separator"],
        "description": "Join a context list into a human-readable string. items is a context ref.",
    },
    "count": {
        "required": ["items"],
        "optional": [],
        "description": "Return the integer length of a context list. items is a context ref.",
    },
    "filter_list": {
        "required": ["items", "condition"],
        "optional": [],
        "description": "Filter a context list to items matching a condition expression. items is a context ref.",
    },
    "extract_field": {
        "required": ["items", "field"],
        "optional": [],
        "description": "Map over a context list of dicts and return just the named field from each. items is a context ref.",
    },
    "slice_list": {
        "required": ["items"],
        "optional": ["start", "end", "limit"],
        "description": "Return a sub-list from a context list. items is a context ref.",
    },
    "merge_text": {
        "required": ["parts"],
        "optional": ["separator"],
        "description": "Concatenate multiple strings. parts is a list of context refs or string literals.",
    },
    "wait": {
        "required": ["seconds"],
        "optional": [],
        "description": "Pause execution for N seconds (capped at 60).",
    },
    "http_request": {
        "required": ["url", "method"],
        "optional": ["headers", "body"],
        "description": "Make a generic HTTP request. method: GET, POST, PUT, PATCH, DELETE.",
    },
    "log": {
        "required": ["message"],
        "optional": ["level"],
        "description": "Write a message to server logs. level: info (default), warning, error.",
    },
    "closest_element": {
        "required": ["items", "target"],
        "optional": ["key"],
        "description": "Find the closest element in a list of strings (or dicts) to a target string using fuzzy matching. items is a context ref. key is optional if items is a list of dicts.",
    },
}


# ─────────────────────────────────────────────
# CONTROL FLOW ACTIONS
# Structural steps that direct execution — no external calls.
# ─────────────────────────────────────────────

CONTROL_ACTIONS: dict[str, dict] = {
    "if": {
        "required": ["condition", "then"],
        "optional": ["else"],
        "description": (
            "Conditional branch. condition is an expression over context values. "
            "then and else are lists of steps."
        ),
    },
    "while": {
        "required": ["condition", "steps"],
        "optional": ["max_iterations"],
        "description": "Loop while condition is truthy. max_iterations defaults to 20 (hard cap 100).",
    },
    "for_each": {
        "required": ["items", "loop_variable", "steps"],
        "optional": [],
        "description": (
            "Iterate over a context list. items is a context ref (e.g. context.results). "
            "loop_variable names the per-iteration binding. steps run once per item."
        ),
    },
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

    # Google Maps
    "google_maps.directions_to_next_event": "Directions from current location to the next calendar event's location",

    # Google Drive
    "google_drive.file_by_name:{name}": "Find a Google Drive file ID by name. Replace {name} with the file name.",
    "google_drive.latest_file": "The most recently modified file in Google Drive",
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

def build_system_prompt(allowed_apps: set[str] | None = None) -> str:
    """
    Build the Gemma system prompt.

    allowed_apps: when provided, only include those app names from ALLOWED_ACTIONS.
    INNATE_ACTIONS and CONTROL_ACTIONS are always included.
    When None, all apps are included (backward-compat / tests).
    """
    # Merge all action dicts; filter ALLOWED_ACTIONS by allowed_apps if given.
    if allowed_apps is None:
        filtered = dict(ALLOWED_ACTIONS)
    else:
        filtered = {k: v for k, v in ALLOWED_ACTIONS.items() if k in allowed_apps}

    all_actions = {**filtered, "innate": INNATE_ACTIONS, "control": CONTROL_ACTIONS}

    apps_block = ""
    for app, actions in all_actions.items():
        apps_block += f"\n  {app}:\n"
        for action, meta in actions.items():
            apps_block += f"    - {action}: required={meta['required']}, optional={meta['optional']}\n"

    resolvers_block = "\n".join(
        f"  {key}: {desc}" for key, desc in RESOLVERS.items()
    )

    denial_rule = ""
    if allowed_apps is not None:
        denial_rule = (
            '\n7. If the user\'s request CANNOT be satisfied by any of the available apps above, '
            'return:\n'
            '   {"intent": "denied", "denial_reason": "<one sentence why>", '
            '"trigger_phrase": "", "steps": [], "missing_params": [], "confidence": 0.0}'
        )

    return f"""You are a workflow parser for a voice-activated automation app.

RULES:
1. You MUST only use apps and actions from the ALLOWED list below. Never invent new ones.
2. For dynamic values, use ONLY resolver keys from the RESOLVERS list. Never hardcode names, emails, or phone numbers.
3. If a step requires an app not in the list, set "unsupported": true on that step and still include it.
4. Return ONLY valid JSON. No markdown, no explanation, no code fences.
5. If you cannot resolve a param, add it to missing_params as a plain English description.
6. Confidence should reflect how well you understood the user's intent (0.0-1.0).{denial_rule}
7. NEVER hardcode or assume dates, times, or timestamps. You do not know what time it is.
   Whenever a step needs the current date or time, you MUST first emit an innate.get_datetime
   step with an output_key, then reference that output in later steps via context.<key>.
   Hardcoding any date string (e.g. "2024-01-01", "today", "now") is forbidden.

ALLOWED APPS AND ACTIONS:
{apps_block}

RESOLVERS (use these keys for dynamic values):
{resolvers_block}

DATA FLOW:
  Any step may include "output_key": "<identifier>" to store its result in the workflow context.
  Reference stored values in later steps using "context.<identifier>" or "context.<identifier>.<field>".
  Example: {{"app": "gmail", "action": "search_email", "params": {{}}, "output_key": "emails"}}
           {{"app": "innate", "action": "count", "params": {{"items": "context.emails"}}, "output_key": "email_count"}}

DATE/TIME PATTERN (always use this when the current date or time is needed):
  Step 1: {{"app": "innate", "action": "get_datetime", "params": {{"format": "iso"}}, "output_key": "now"}}
  Step 2: use "context.now" wherever the timestamp is needed as a param value.
  Never skip step 1 and never substitute a hardcoded date string for "context.now".

CONTROL FLOW SYNTAX:
  control.if:
    {{"app": "control", "action": "if", "condition": "context.count > 0", "then": [...steps...], "else": [...steps...]}}
  control.while:
    {{"app": "control", "action": "while", "condition": "context.retries < 3", "steps": [...steps...], "max_iterations": 20}}
  control.for_each:
    {{"app": "control", "action": "for_each", "items": "context.email_list", "loop_variable": "item", "steps": [...steps...]}}
  Conditions may reference context keys: context.count > 0 | context.status == "ok" | context.found is not None

OUTPUT SCHEMA:
{{
  "intent": "create_workflow" | "trigger_workflow" | "other" | "denied",
  "denial_reason": "<only present when intent is denied>",
  "trigger_phrase": "<phrase that activates this workflow>",
  "steps": [
    {{
      "app": "<app name>",
      "action": "<action name>",
      "params": {{"<param_name>": "<static value, resolver key, or context.ref>"}},
      "unsupported": false,
      "output_key": "<optional: store result in context under this name>",
      // control.if only: "condition", "then", "else"
      // control.while only: "condition", "steps", "max_iterations"
      // control.for_each only: "items", "loop_variable", "steps"
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