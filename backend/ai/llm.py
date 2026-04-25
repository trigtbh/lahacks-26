"""
llm.py
Single source of truth for LLM access across the AI layer.

Every other AI file (classifier, validator, resolver, dialogue, executor)
imports from here. Do NOT instantiate genai.Client elsewhere.

Supports the new google-genai SDK and is model-swappable via LLM_MODEL env var.
Tested with gemini-2.5-flash and gemma-4-* models for the hackathon Gemma track.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types


# Load .env from the ai/ dir first (this file's neighbour), then fall back to
# the project root or cwd. load_dotenv does not override existing env vars,
# so order is safe.
_AI_DIR = Path(__file__).parent
load_dotenv(_AI_DIR / ".env")
load_dotenv(_AI_DIR.parent / ".env")
load_dotenv()


_DEFAULT_MODEL = "gemini-2.5-flash"


def _get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY in .env."
        )
    return key


def _get_model() -> str:
    return os.getenv("LLM_MODEL", _DEFAULT_MODEL)


def _is_gemma(model: str) -> bool:
    """Gemma models share the same client but don't support response_mime_type."""
    return model.lower().startswith("gemma")


# Module-level client. Single instance shared across the AI layer.
client = genai.Client(api_key=_get_api_key())


# ─────────────────────────────────────────────
# Fence stripping (Gemma fallback only — Gemini in JSON mode returns clean JSON)
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

    For Gemini: uses response_mime_type="application/json" so the model returns
    a clean JSON string with no markdown fences.
    For Gemma: omits response_mime_type (unsupported) and strips fences as fallback.

    Raises:
        ValueError: if the response is not parseable JSON or not a JSON object.
    """
    model = _get_model()
    config_kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
    }
    if not _is_gemma(model):
        config_kwargs["response_mime_type"] = "application/json"

    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )

    raw = response.text or ""
    if _is_gemma(model):
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
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        ),
    )
    return (response.text or "").strip()
