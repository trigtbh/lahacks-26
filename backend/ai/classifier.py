"""
classifier.py
Stage 1 of the anti-hallucination pipeline.
Transcript -> workflow JSON, constrained by environment.py / prompts.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ai.llm import generate_json
from ai.prompts import CLASSIFIER_SYSTEM, build_classifier_user_prompt
from ai.validator import validate, repair


def classify(transcript: str, system_prompt: str | None = None) -> dict[str, Any]:
    """
    Convert a raw transcript into a workflow JSON dict, then validate and repair.

    system_prompt: override the default CLASSIFIER_SYSTEM (e.g. pass
    a filtered prompt from build_filtered_system_prompt() for per-user context).
    """
    prompt = system_prompt if system_prompt is not None else CLASSIFIER_SYSTEM
    user_prompt = build_classifier_user_prompt(transcript)
    workflow = generate_json(prompt, user_prompt)

    errors = validate(workflow)
    if errors:
        workflow = repair(workflow, errors)

    return workflow


async def classify_for_user(transcript: str, user_id: str) -> dict[str, Any]:
    """
    Classify with a system prompt filtered to only the apps this user has connected.
    Preferred over classify() for all production call sites.
    """
    from ai.prompts import build_filtered_system_prompt
    system_prompt = await build_filtered_system_prompt(user_id)
    return await asyncio.to_thread(classify, transcript, system_prompt)
