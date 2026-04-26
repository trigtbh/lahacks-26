"""
innate_executor.py
Handlers for the 'innate' app — built-in actions that run locally
with no OAuth or external API required.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

import variable_store

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


# ─────────────────────────────────────────────
# Template interpolation shared by format_text and calculate
# ─────────────────────────────────────────────

def _interpolate(template: str, context: dict) -> str:
    """Replace {{context.key}} and {{context.key.sub}} with context values."""
    def _replace(m: re.Match) -> str:
        path = m.group(1).strip()
        if path.startswith("context."):
            path = path[len("context."):]
        val = _get_nested_path(path, context)
        return str(val) if val is not None else ""

    return re.sub(r"\{\{([^}]+)\}\}", _replace, template)


def _get_nested_path(path: str, obj: Any) -> Any:
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, (list, tuple)):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return obj


def _resolve_items(items_ref: Any, context: dict) -> list:
    """Resolve an items parameter — either a context ref string or a literal list."""
    if isinstance(items_ref, str) and items_ref.startswith("context."):
        val = _get_nested_path(items_ref[len("context."):], context)
        return list(val) if isinstance(val, (list, tuple)) else []
    if isinstance(items_ref, list):
        return items_ref
    return []


# ─────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────

async def _get_datetime(user_id: str, params: dict, context: dict) -> str:
    fmt = params.get("format", "iso")
    tz_name = params.get("timezone", "UTC")
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    if fmt == "human":
        return now.strftime("%A, %B %-d %Y at %-I:%M %p %Z")
    if fmt == "date_only":
        return now.strftime("%Y-%m-%d")
    if fmt == "time_only":
        return now.strftime("%H:%M:%S")
    return now.isoformat()


async def _get_user_info(user_id: str, params: dict, context: dict) -> Any:
    import token_store
    field = params.get("field")
    # Try to get profile from stored Google token
    doc = await token_store.get_token(user_id, "google")
    profile: dict = {}
    if doc:
        profile = {
            "user_id": user_id,
            "email":   doc.get("email", ""),
            "name":    doc.get("name", ""),
        }
    else:
        profile = {"user_id": user_id, "email": "", "name": ""}
    if field:
        return profile.get(field, "")
    return profile


async def _set_variable(user_id: str, params: dict, context: dict) -> Any:
    value = params.get("value")
    key = params.get("key", "")
    scope = params.get("scope", "local").lower()
    
    if key:
        context[key] = value
        if scope == "global":
            await variable_store.set_global_variable(user_id, key, value)
            
    return value


async def _get_variable(user_id: str, params: dict, context: dict) -> Any:
    key = params["key"]
    default = params.get("default")
    
    # Check local context first
    if key in context:
        return context[key]
        
    # Fallback to global store
    global_val = await variable_store.get_global_variable(user_id, key, None)
    if global_val is not None:
        return global_val
        
    return default


async def _calculate(user_id: str, params: dict, context: dict) -> Any:
    expression = _interpolate(str(params["expression"]), context)
    # Safe numeric eval — only allow numbers, arithmetic ops, parens
    safe_expr = re.sub(r"[^0-9+\-*/().\s%]", "", expression)
    if not safe_expr.strip():
        return 0
    try:
        result = eval(safe_expr, {"__builtins__": {}})  # noqa: S307
        return result
    except Exception as e:
        log.warning("innate.calculate: error evaluating %r: %s", safe_expr, e)
        return 0


async def _datetime_math(user_id: str, params: dict, context: dict) -> str:
    from datetime import timedelta
    
    base_time_str = str(params.get("base_time", ""))
    operation = str(params.get("operation", "add")).lower()
    amount = float(params.get("amount", 0))
    unit = str(params.get("unit", "days")).lower()
    fmt = str(params.get("format", "iso")).lower()
    
    try:
        base_time = datetime.fromisoformat(base_time_str.replace("Z", "+00:00"))
    except ValueError:
        base_time = datetime.now(timezone.utc)
        
    # Map friendly units to timedelta args
    if unit in ("year", "years"):
        delta = timedelta(days=amount * 365)
    elif unit in ("month", "months"):
        delta = timedelta(days=amount * 30)
    elif unit in ("week", "weeks"):
        delta = timedelta(weeks=amount)
    elif unit in ("hour", "hours"):
        delta = timedelta(hours=amount)
    elif unit in ("minute", "minutes"):
        delta = timedelta(minutes=amount)
    elif unit in ("second", "seconds"):
        delta = timedelta(seconds=amount)
    else:
        delta = timedelta(days=amount)
        
    if operation == "subtract":
        result_time = base_time - delta
    else:
        result_time = base_time + delta
        
    if fmt == "human":
        return result_time.strftime("%A, %B %d, %Y at %I:%M %p").replace(" 0", " ")
    elif fmt == "date_only":
        return result_time.strftime("%Y-%m-%d")
    elif fmt == "time_only":
        return result_time.strftime("%H:%M:%S")
    return result_time.isoformat()


async def _format_text(user_id: str, params: dict, context: dict) -> str:
    return _interpolate(str(params["template"]), context)


async def _join_list(user_id: str, params: dict, context: dict) -> str:
    items = _resolve_items(params["items"], context)
    sep = params.get("separator", ", ")
    final_sep = params.get("final_separator", sep)
    strs = [str(i) for i in items]
    if len(strs) <= 1:
        return strs[0] if strs else ""
    return sep.join(strs[:-1]) + final_sep + strs[-1]


async def _count(user_id: str, params: dict, context: dict) -> int:
    return len(_resolve_items(params["items"], context))


async def _filter_list(user_id: str, params: dict, context: dict) -> list:
    from ai.condition_eval import evaluate_condition
    items = _resolve_items(params["items"], context)
    cond = str(params["condition"])
    result = []
    for item in items:
        item_ctx = {**context, "item": item}
        if evaluate_condition(cond.replace("context.item", "context.item"), item_ctx):
            result.append(item)
    return result


async def _extract_field(user_id: str, params: dict, context: dict) -> list:
    items = _resolve_items(params["items"], context)
    field = str(params["field"])
    return [i.get(field) if isinstance(i, dict) else None for i in items]


async def _slice_list(user_id: str, params: dict, context: dict) -> list:
    items = _resolve_items(params["items"], context)
    start = int(params.get("start", 0))
    limit = params.get("limit")
    end = params.get("end")
    if limit is not None:
        end = start + int(limit)
    elif end is not None:
        end = int(end)
    return items[start:end]


async def _merge_text(user_id: str, params: dict, context: dict) -> str:
    sep = params.get("separator", "")
    parts_raw = params.get("parts", [])
    if isinstance(parts_raw, str):
        parts_raw = [parts_raw]
    parts = []
    for p in parts_raw:
        if isinstance(p, str) and p.startswith("context."):
            val = _get_nested_path(p[len("context."):], context)
            parts.append(str(val) if val is not None else "")
        else:
            parts.append(str(p))
    return sep.join(parts)


async def _wait(user_id: str, params: dict, context: dict) -> None:
    seconds = min(float(params.get("seconds", 1)), 60.0)
    await asyncio.sleep(seconds)


async def _http_request(user_id: str, params: dict, context: dict) -> Any:
    url = str(params["url"])
    method = str(params.get("method", "GET")).upper()
    headers = params.get("headers", {}) or {}
    body = params.get("body")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, url, headers=headers, json=body)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return resp.text


async def _ai_summarize(user_id: str, params: dict, context: dict) -> str:
    from ai.llm import generate_text
    content = params.get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(item) for item in content)
    elif not isinstance(content, str):
        content = str(content)
    instruction = params.get("instruction", "Summarize the following content concisely in plain English.")
    return generate_text(instruction, content)


async def _log(user_id: str, params: dict, context: dict) -> None:
    level = str(params.get("level", "info")).lower()
    msg = str(params.get("message", ""))
    getattr(log, level if level in ("info", "warning", "error") else "info")(
        "[innate.log] user=%s: %s", user_id, msg
    )


async def _closest_element(user_id: str, params: dict, context: dict) -> Any:
    import difflib
    items = _resolve_items(params["items"], context)
    target = str(params["target"]).lower()
    key = params.get("key")

    if not items:
        return None

    best_match = None
    best_score = -1.0

    for item in items:
        # Determine the string to compare
        if key and isinstance(item, dict):
            val_str = str(item.get(key, "")).lower()
        else:
            val_str = str(item).lower()

        score = difflib.SequenceMatcher(None, target, val_str).ratio()
        if score > best_score:
            best_score = score
            best_match = item

    return best_match


# ─────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────

_HANDLERS = {
    "get_datetime":  _get_datetime,
    "datetime_math": _datetime_math,
    "get_user_info": _get_user_info,
    "set_variable":  _set_variable,
    "get_variable":  _get_variable,
    "calculate":     _calculate,
    "format_text":   _format_text,
    "join_list":     _join_list,
    "count":         _count,
    "filter_list":   _filter_list,
    "extract_field": _extract_field,
    "slice_list":    _slice_list,
    "merge_text":    _merge_text,
    "wait":          _wait,
    "http_request":  _http_request,
    "log":           _log,
    "closest_element": _closest_element,
    "ai_summarize":    _ai_summarize,
}


async def execute_innate(user_id: str, action: str, params: dict, context: dict) -> Any:
    handler = _HANDLERS.get(action)
    if handler is None:
        raise ValueError(f"innate: unknown action '{action}'")
    return await handler(user_id, params, context)
