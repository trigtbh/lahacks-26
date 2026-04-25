"""
validator.py
Stage 2 of the anti-hallucination pipeline.

validate() is a pure, side-effect-free check of the workflow JSON.
repair() asks the LLM to fix a flagged workflow, with a re-validate-and-retry loop.
"""

from __future__ import annotations

import re
from typing import Any

from ai.environment import ALLOWED_ACTIONS, is_resolver
from ai.llm import generate_json
from ai.prompts import VALIDATOR_SYSTEM, build_validator_repair_prompt


_VALID_INTENTS = {"create_workflow", "trigger_workflow", "other"}

# Heuristic: does this string LOOK like it was meant to be a resolver?
# Matches dotted lowercase identifiers, optionally with `:` or `+` template suffix.
# - calendar.next_event.attendees           ✓
# - user.contacts.by_name:Sarah             ✓
# - time.now+15m                            ✓
# - team@example.com                        ✗ (has @)
# - "Running late"                          ✗ (has space)
# - 3.14                                    ✗ (starts with digit)
_RESOLVER_SHAPE_RE = re.compile(
    r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+(?:[:+].*)?$",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────

def validate(workflow: dict, allowed_actions: dict | None = None) -> list[str]:
    """
    Check a workflow JSON against the closed-world schema.

    Returns a list of human-readable error strings. Empty list = clean.
    Never raises — soft-fail is the contract so the caller can decide what to do.

    allowed_actions: override the default ALLOWED_ACTIONS (e.g. pass
    EXTENDED_ACTIONS from environment_extensions to validate against the
    extended schema).
    """
    _allowed = allowed_actions if allowed_actions is not None else ALLOWED_ACTIONS
    errors: list[str] = []

    if not isinstance(workflow, dict):
        return [f"workflow is not a JSON object (got {type(workflow).__name__})"]

    _check_top_level(workflow, errors)
    _check_intent(workflow, errors)
    _check_confidence(workflow, errors)
    _check_steps(workflow, errors, _allowed)

    return errors


def _check_top_level(workflow: dict, errors: list[str]) -> None:
    expected_keys = ("intent", "trigger_phrase", "steps", "missing_params", "confidence")
    for key in expected_keys:
        if key not in workflow:
            errors.append(f"top-level: missing required key '{key}'")

    if "trigger_phrase" in workflow and not isinstance(workflow["trigger_phrase"], str):
        errors.append(
            f"top-level: 'trigger_phrase' must be a string "
            f"(got {type(workflow['trigger_phrase']).__name__})"
        )
    if "steps" in workflow and not isinstance(workflow["steps"], list):
        errors.append(
            f"top-level: 'steps' must be a list "
            f"(got {type(workflow['steps']).__name__})"
        )
    if "missing_params" in workflow and not isinstance(workflow["missing_params"], list):
        errors.append(
            f"top-level: 'missing_params' must be a list "
            f"(got {type(workflow['missing_params']).__name__})"
        )


def _check_intent(workflow: dict, errors: list[str]) -> None:
    intent = workflow.get("intent")
    if intent is None:
        return  # already reported by _check_top_level if missing
    if intent not in _VALID_INTENTS:
        errors.append(
            f"top-level: intent '{intent}' is not one of {sorted(_VALID_INTENTS)}"
        )


def _check_confidence(workflow: dict, errors: list[str]) -> None:
    if "confidence" not in workflow:
        return
    conf = workflow["confidence"]
    # bool is a subclass of int in Python — exclude it explicitly.
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        errors.append(f"top-level: confidence must be a number (got {conf!r})")
        return
    if not (0.0 <= float(conf) <= 1.0):
        errors.append(f"top-level: confidence {conf} is out of range [0.0, 1.0]")


def _check_steps(workflow: dict, errors: list[str], allowed_actions: dict) -> None:
    steps = workflow.get("steps")
    if not isinstance(steps, list):
        return  # already reported

    for i, step in enumerate(steps):
        prefix = f"step {i}"
        if not isinstance(step, dict):
            errors.append(f"{prefix}: not a JSON object (got {type(step).__name__})")
            continue

        # Skip body validation if the step was flagged as unsupported by the classifier.
        if step.get("unsupported") is True:
            continue

        app = step.get("app")
        action = step.get("action")
        action_label = f"{app}.{action}" if app and action else "?"
        prefix = f"step {i} ({action_label})"

        # app
        if not isinstance(app, str) or not app:
            errors.append(f"step {i}: missing or non-string 'app'")
            continue
        if app not in allowed_actions:
            errors.append(
                f"{prefix}: unknown app '{app}'. "
                f"Allowed: {sorted(allowed_actions.keys())}"
            )
            continue

        # action
        if not isinstance(action, str) or not action:
            errors.append(f"{prefix}: missing or non-string 'action'")
            continue
        if action not in allowed_actions[app]:
            errors.append(
                f"{prefix}: unknown action '{action}' for app '{app}'. "
                f"Allowed: {sorted(allowed_actions[app].keys())}"
            )
            continue

        # params
        params = step.get("params")
        if not isinstance(params, dict):
            errors.append(
                f"{prefix}: 'params' must be a JSON object "
                f"(got {type(params).__name__ if params is not None else 'missing'})"
            )
            continue

        required = allowed_actions[app][action]["required"]
        for req in required:
            if req not in params:
                errors.append(f"{prefix}: missing required param '{req}'")
            elif params.get(req) is None:
                errors.append(f"{prefix}: required param '{req}' is None")

        # Resolver-shape values must actually be valid resolvers.
        for pname, pvalue in params.items():
            if isinstance(pvalue, str) and _looks_like_resolver(pvalue):
                if not is_resolver(pvalue):
                    errors.append(
                        f"{prefix}: param '{pname}' value '{pvalue}' "
                        f"looks like a resolver but is not a known resolver key"
                    )


def _looks_like_resolver(value: str) -> bool:
    return bool(_RESOLVER_SHAPE_RE.match(value))


# ─────────────────────────────────────────────
# repair
# ─────────────────────────────────────────────

def repair(workflow: dict, errors: list[str], max_retries: int = 2) -> dict:
    """
    Ask the LLM to fix a workflow flagged by validate().

    If errors is empty, returns workflow unchanged.

    Otherwise, sends workflow + errors to the LLM up to `max_retries` times,
    re-validating after each attempt. Returns the first clean repair.

    If the workflow is still dirty after all retries, returns the latest attempt
    with the remaining errors attached as workflow["_validation_errors"] so the
    downstream caller can decide whether to surface or ignore them.
    """
    if not errors:
        return workflow

    current: dict = workflow
    current_errors: list[str] = list(errors)

    for attempt in range(1, max_retries + 1):
        prompt = build_validator_repair_prompt(current, current_errors)
        try:
            repaired = generate_json(VALIDATOR_SYSTEM, prompt)
        except ValueError as e:
            tagged = dict(current)
            tagged["_validation_errors"] = current_errors + [
                f"repair attempt {attempt}: LLM returned unparseable JSON ({e})"
            ]
            return tagged

        current = repaired
        current_errors = validate(current)
        if not current_errors:
            return current

    # Still dirty after max_retries.
    tagged = dict(current)
    tagged["_validation_errors"] = current_errors
    return tagged
