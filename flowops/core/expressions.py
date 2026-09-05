"""Bounded data-only path expressions. No Python execution, functions or attribute access.

Full expressions preserve types; interpolation permits only scalar values. Paths traverse
plain dictionaries/lists and missing values fail closed. For Each evaluates its template
explicitly per item, instead of introducing graph cycles.
"""

import copy
import re
from typing import Any

from flowops.domain.errors import WorkflowValidationError

EXPRESSION = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*|\[\d{1,6}\])*$")
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*|\[(\d+)\]")
ROOTS = {"params", "nodes", "item", "input", "context"}


def path_parts(path: str) -> list[str | int]:
    path = path.strip()
    if len(path) > 1024 or not PATH.fullmatch(path):
        raise WorkflowValidationError("Invalid data path; use names, dots and numeric indices.")
    return [int(m.group(1)) if m.group(1) is not None else m.group() for m in TOKEN.finditer(path)]


def lookup(path: str, scope: dict[str, Any]) -> Any:
    parts = path_parts(path)
    if parts[0] not in ROOTS:
        raise WorkflowValidationError(
            "Expression root must be params, nodes, item, input or context."
        )
    value: Any = scope
    for part in parts:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, list) and isinstance(part, int) and part < len(value):
            value = value[part]
        else:
            raise WorkflowValidationError(f"Missing output or parameter at {path}.")
    if value == "[REDACTED]" or (isinstance(value, dict) and value.get("_truncated")):
        raise WorkflowValidationError("Redacted or truncated data cannot feed another action.")
    return copy.deepcopy(value)


def references(value: Any, depth: int = 0) -> list[str]:
    if depth > 32:
        raise WorkflowValidationError("Configuration nesting exceeds 32 levels.")
    if isinstance(value, str):
        matches = [match.group(1).strip() for match in EXPRESSION.finditer(value)]
        for path in matches:
            path_parts(path)
        residue = EXPRESSION.sub("", value)
        if "{{" in residue or "}}" in residue:
            raise WorkflowValidationError("Malformed expression delimiters.")
        return matches
    if isinstance(value, dict):
        return [r for v in value.values() for r in references(v, depth + 1)]
    if isinstance(value, list):
        return [r for v in value for r in references(v, depth + 1)]
    return []


def resolve(value: Any, scope: dict[str, Any], depth: int = 0) -> Any:
    if depth > 32:
        raise WorkflowValidationError("Configuration nesting exceeds 32 levels.")
    if isinstance(value, dict):
        return {k: resolve(v, scope, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope, depth + 1) for v in value]
    if not isinstance(value, str):
        return value
    references(value)
    full = EXPRESSION.fullmatch(value.strip())
    if full:
        return lookup(full.group(1), scope)

    def replace(match: re.Match[str]) -> str:
        result = lookup(match.group(1), scope)
        if isinstance(result, (list, dict)):
            raise WorkflowValidationError("Map structured values using a full expression.")
        return str(result)

    return EXPRESSION.sub(replace, value)


def compare(left: Any, operator: str, right: Any = None) -> bool:
    """Small explicit predicate vocabulary; comparison errors never become truthy."""
    if operator == "eq":
        return type(left) is type(right) and left == right
    if operator == "ne":
        return not compare(left, "eq", right)
    if operator == "exists":
        return left is not None
    if operator == "truthy":
        return bool(left)
    try:
        if operator == "gt":
            return bool(left > right)
        if operator == "gte":
            return bool(left >= right)
        if operator == "lt":
            return bool(left < right)
        if operator == "lte":
            return bool(left <= right)
        if operator == "in":
            return left in right
        if operator == "contains":
            return right in left
    except (TypeError, ValueError) as exc:
        raise WorkflowValidationError("Predicate received incompatible types.") from exc
    raise WorkflowValidationError(f"Unknown predicate: {operator}.")
