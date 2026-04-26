"""
llm.py
Single source of truth for LLM access across the AI layer.

Every other AI file (classifier, validator, resolver, dialogue, executor)
imports from here. Do NOT instantiate OpenAI clients elsewhere.

Uses the OpenAI SDK pointed at OpenRouter to access Gemma models.
Model is swappable via LLM_MODEL env var.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


# Load .env from the ai/ dir first (this file's neighbour), then fall back to
# the project root or cwd. load_dotenv does not override existing env vars,
# so order is safe.
_AI_DIR = Path(__file__).parent
load_dotenv(_AI_DIR / ".env")
load_dotenv(_AI_DIR.parent / ".env")
load_dotenv()


_DEFAULT_MODEL = "google/gemma-4-26b-a4b-it"


def _get_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set OPENROUTER_API_KEY in .env."
        )
    return key


def _get_model() -> str:
    return os.getenv("LLM_MODEL", _DEFAULT_MODEL)


# Module-level client. Single instance shared across the AI layer.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=_get_api_key(),
)


# ─────────────────────────────────────────────
# Fence stripping (Gemma doesn't support response_format=json reliably)
# ─────────────────────────────────────────────

_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")


def _strip_fences(text: str) -> str:
    text = _FENCE_OPEN_RE.sub("", text, count=1)
    text = _FENCE_CLOSE_RE.sub("", text, count=1)
    return text.strip()


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def generate_json(
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """
    Call the LLM and parse its response as a JSON object.

    Always strips markdown fences as a safety net, since Gemma models
    may wrap JSON in ```json ... ``` blocks.

    Raises:
        ValueError: if the response is not parseable JSON or not a JSON object.
    """
    model = _get_model()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )

    raw = response.choices[0].message.content or ""
    raw = _strip_fences(raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM ({model}) returned unparseable JSON: {e.msg} at pos {e.pos}\n"
            f"--- raw response ---\n{raw}\n--- end ---"
        ) from e

    if not isinstance(parsed, dict):
        raise ValueError(
            f"LLM ({model}) returned JSON of type {type(parsed).__name__}, "
            f"expected object."
        )
    return parsed


def generate_json_coerce(
    system_instruction: str,
    user_prompt: str,
    list_key: str,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """
    Like generate_json but tolerates a bare JSON array response by wrapping it
    in { list_key: <array>, "has_clarifications": false }.
    Use this when the LLM is known to sometimes return a list instead of an object.
    """
    model = _get_model()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )

    raw = response.choices[0].message.content or ""
    raw = _strip_fences(raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM ({model}) returned unparseable JSON: {e.msg} at pos {e.pos}\n"
            f"--- raw response ---\n{raw}\n--- end ---"
        ) from e

    if isinstance(parsed, list):
        return {list_key: parsed, "has_clarifications": False}

    if not isinstance(parsed, dict):
        raise ValueError(
            f"LLM ({model}) returned JSON of type {type(parsed).__name__}, "
            f"expected object."
        )
    return parsed


def generate_text(
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.7,
) -> str:
    """
    Call the LLM and return its raw text response.

    Used by dialogue.py for plain-English voice questions where JSON would be wrong.
    """
    model = _get_model()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip()
