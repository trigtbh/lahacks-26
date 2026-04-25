"""
classifier.py
Stage 1 of the anti-hallucination pipeline.
Transcript -> workflow JSON, constrained by environment.py / prompts.py.
"""

from __future__ import annotations

from typing import Any

from ai.llm import generate_json
from ai.prompts import CLASSIFIER_SYSTEM, build_classifier_user_prompt


def classify(transcript: str, system_prompt: str | None = None) -> dict[str, Any]:
    """
    Convert a raw transcript into a workflow JSON dict.

    Returns the parsed JSON exactly as the LLM produced it — no validation,
    no repair. validator.py is responsible for everything after this.

    system_prompt: override the default CLASSIFIER_SYSTEM (e.g. pass
    get_extended_system_prompt() to use the extended schema).
    """
    prompt = system_prompt if system_prompt is not None else CLASSIFIER_SYSTEM
    user_prompt = build_classifier_user_prompt(transcript)
    return generate_json(prompt, user_prompt)
