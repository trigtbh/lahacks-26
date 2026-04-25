"""
condition_eval.py
Safe boolean expression evaluator for workflow control flow conditions.

Parses expressions with ast.parse(), validates the AST against a strict
whitelist of node types, then evaluates with an empty __builtins__ namespace.
Returns False (never raises) on any malformed or unsafe input.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

log = logging.getLogger(__name__)

# AST node types that are allowed anywhere in the expression tree.
_ALLOWED_NODES = {
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not,
    ast.Compare,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
    ast.Constant,
    ast.Name,
    ast.Attribute,
    ast.List, ast.Tuple, ast.Load,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.IfExp,  # ternary: a if cond else b
    ast.Call,
}

# Methods allowed on string/list objects inside conditions.
_ALLOWED_METHODS = {"startswith", "endswith", "lower", "upper", "strip", "split", "count"}


def _check_node(node: ast.AST) -> bool:
    """Return False if the node or any descendant is not in the whitelist."""
    if type(node) not in _ALLOWED_NODES:
        return False

    # ast.Name is only allowed for the literals None/True/False and "context"
    if isinstance(node, ast.Name):
        if node.id not in ("None", "True", "False", "context", "len", "str", "int", "float"):
            return False

    # ast.Call is only allowed for whitelisted method names or len()
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr not in _ALLOWED_METHODS:
                return False
        elif isinstance(func, ast.Name):
            if func.id not in ("len", "str", "int", "float"):
                return False
        else:
            return False
        # No *args / **kwargs
        if node.starargs if hasattr(node, "starargs") else False:
            return False
        if node.kwargs if hasattr(node, "kwargs") else False:
            return False

    return all(_check_node(child) for child in ast.iter_child_nodes(node))


def _resolve_context_attr(node: ast.Attribute, context: dict) -> Any:
    """
    Recursively resolve an attribute chain rooted at 'context'.
    e.g. context.emails.first -> context["emails"]["first"]
    Returns a sentinel _MISSING if the chain cannot be resolved.
    """
    if isinstance(node.value, ast.Name) and node.value.id == "context":
        return _get_nested(context, node.attr)
    if isinstance(node.value, ast.Attribute):
        parent = _resolve_context_attr(node.value, context)
        if parent is _MISSING:
            return _MISSING
        if isinstance(parent, dict):
            return parent.get(node.attr, _MISSING)
        return _MISSING
    return _MISSING


_MISSING = object()


def _get_nested(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, _MISSING)
    if isinstance(obj, (list, tuple)):
        try:
            return obj[int(key)]
        except (ValueError, IndexError):
            return _MISSING
    return _MISSING


class _ContextProxy:
    """Wraps the context dict so attribute access (context.key) works in eval."""
    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, key: str) -> Any:
        val = self._data.get(key, _MISSING)
        if val is _MISSING:
            return None
        if isinstance(val, dict):
            return _ContextProxy(val)
        return val

    def __contains__(self, item: Any) -> bool:
        return item in self._data

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)


def evaluate_condition(expression: str, context: dict) -> bool:
    """
    Safely evaluate a boolean condition expression against a context dict.

    Supported syntax:
      context.x > 5            context.name == "Alice"
      context.count is not None context.flag and context.ready
      not context.done          "value" in context.list
      context.msg.startswith("hello")   len(context.items) > 0

    Returns False on any parse error, unsafe node, or evaluation error.
    """
    if not isinstance(expression, str) or not expression.strip():
        return False

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        log.warning("condition_eval: parse error in %r: %s", expression, e)
        return False

    if not _check_node(tree):
        log.warning("condition_eval: unsafe AST node in %r", expression)
        return False

    safe_ns: dict[str, Any] = {
        "__builtins__": {},
        "context": _ContextProxy(context),
        "None": None,
        "True": True,
        "False": False,
        "len": len,
        "str": str,
        "int": int,
        "float": float,
    }

    try:
        result = eval(compile(tree, "<condition>", "eval"), safe_ns)  # noqa: S307
        return bool(result)
    except Exception as e:
        log.warning("condition_eval: eval error in %r: %s", expression, e)
        return False
