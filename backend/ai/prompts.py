"""
prompts.py
All Gemini prompt strings and user prompt builders.
This is the only file you edit when tuning AI behaviour.
classifier.py, dialogue.py, validator.py all import from here.
"""

from ai.environment import build_system_prompt, RESOLVERS, ALLOWED_ACTIONS, INNATE_ACTIONS, CONTROL_ACTIONS


# ─────────────────────────────────────────────
# CLASSIFIER PROMPTS
# Used in classifier.py — transcript → workflow JSON
# ─────────────────────────────────────────────

CLASSIFIER_SYSTEM = build_system_prompt()


async def build_filtered_system_prompt(user_id: str) -> str:
    """Build a system prompt filtered to only the apps this user has connected."""
    from ai.app_resolver import get_available_apps
    available = await get_available_apps(user_id)
    return build_system_prompt(allowed_apps=available)


def build_classifier_user_prompt(transcript: str) -> str:
    return f"""The user said the following via voice:

"{transcript}"

If they are describing a workflow they want to create, extract it as JSON.
If they are triggering an existing workflow, set intent to "trigger_workflow".
If it's neither, set intent to "other".

Return ONLY the JSON. No explanation."""


# ─────────────────────────────────────────────
# DIALOGUE PROMPTS
# Used in dialogue.py — asking user for missing params
# ─────────────────────────────────────────────

DIALOGUE_SYSTEM = """You are a voice assistant helping a user complete a workflow setup.
Your job is to ask ONE clear, conversational question to get a missing piece of information.
Keep it short — one sentence max. Speak like a human, not a bot.
Never ask for multiple things at once.
Never explain what a workflow is."""


def build_dialogue_user_prompt(missing_param: str, workflow_context: dict) -> str:
    trigger = workflow_context.get("trigger_phrase", "this workflow")
    steps_summary = ", ".join(
        f"{s['app']} {s['action']}" for s in workflow_context.get("steps", [])
    )
    return f"""The user is setting up a workflow triggered by: "{trigger}"
The workflow will: {steps_summary}

We are missing: {missing_param}

Write a single conversational question to ask the user for this information."""


def build_dialogue_resolve_prompt(missing_param: str, user_answer: str, workflow_context: dict) -> str:
    resolver_keys = list(RESOLVERS.keys())
    return f"""The user was asked about: {missing_param}
They answered: "{user_answer}"

Workflow context: {workflow_context}

Your job: extract the value from their answer and return JSON like this:
{{
  "resolved_value": "<the extracted value or a resolver key if dynamic>",
  "confident": true,
  "confidence_score": 0.95
}}

If the answer maps to a dynamic resolver, use the resolver key instead of a static value.
Available resolver keys: {resolver_keys}

If you are not confident (score below 0.8), set confident to false.
Return ONLY the JSON."""


# ─────────────────────────────────────────────
# VALIDATOR PROMPTS
# Used in validator.py — fixing bad Gemini output
# ─────────────────────────────────────────────

VALIDATOR_SYSTEM = """You are a JSON repair agent. You will receive a broken or invalid workflow JSON
and a list of specific errors. Fix ONLY the listed errors. Do not change anything else.
Return ONLY the corrected JSON. No explanation."""


def build_validator_repair_prompt(workflow_json: dict, errors: list[str]) -> str:
    allowed_apps = list({**ALLOWED_ACTIONS, "innate": INNATE_ACTIONS, "control": CONTROL_ACTIONS}.keys())
    resolver_keys = list(RESOLVERS.keys())
    return f"""This workflow JSON has errors:

WORKFLOW:
{workflow_json}

ERRORS TO FIX:
{chr(10).join(f"- {e}" for e in errors)}

ALLOWED APPS: {allowed_apps}
ALLOWED RESOLVER KEYS: {resolver_keys}

Fix only the listed errors and return the corrected JSON."""


# ─────────────────────────────────────────────
# EXECUTOR PROMPTS
# Used in executor.py — filling dynamic params at runtime
# ─────────────────────────────────────────────

EXECUTOR_SYSTEM = """You are a plain English summariser for a voice assistant.
You will receive the result of an automated workflow execution.
Summarise what happened in one or two short sentences, spoken naturally.
Do not use technical terms. Do not mention API calls or JSON."""


def build_executor_summary_prompt(steps_completed: list[dict], steps_failed: list[dict]) -> str:
    completed_str = "\n".join(
        f"- {s['app']} {s['action']}: SUCCESS" for s in steps_completed
    )
    failed_str = "\n".join(
        f"- {s['app']} {s['action']}: FAILED — {s.get('error', 'unknown error')}" for s in steps_failed
    )
    return f"""Workflow execution complete.

COMPLETED:
{completed_str or 'None'}

FAILED:
{failed_str or 'None'}

Summarise this in plain English for the user to hear via voice."""


# ─────────────────────────────────────────────
# TRIGGER MATCHING PROMPT
# Used when deciding if a spoken phrase fires an existing workflow
# ─────────────────────────────────────────────

TRIGGER_SYSTEM = """You are a trigger phrase matcher for a voice automation app.
Given a spoken phrase and a list of saved workflow trigger phrases,
decide if the spoken phrase is close enough to fire one of them.
Fuzzy matching is fine — the user does not need to say it word-for-word.
Return ONLY JSON."""


def build_trigger_match_prompt(spoken: str, saved_triggers: list[str]) -> str:
    return f"""Spoken phrase: "{spoken}"

Saved trigger phrases:
{chr(10).join(f'- "{t}"' for t in saved_triggers)}

If the spoken phrase matches one of the saved triggers, return:
{{
  "matched": true,
  "trigger_phrase": "<the matched trigger phrase>",
  "confidence": 0.95
}}

If no match, return:
{{
  "matched": false,
  "trigger_phrase": null,
  "confidence": 0.0
}}"""