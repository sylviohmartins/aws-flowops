"""Pure, bounded logic nodes. Time, approval and provider calls belong to the engine."""

from typing import Any

from flowops.core.expressions import compare, lookup, resolve
from flowops.domain.errors import WorkflowValidationError


def logic(action: str, config: dict[str, Any], scope: dict[str, Any], limit: int = 1000) -> tuple[Any, str]:
    if action in {"core.start", "core.end", "core.parallel"}:
        return config.get("value", {}), "default"
    if action == "core.merge":
        return config.get("inputs", scope.get("input", {})), "default"
    if action == "core.stop":
        return {"reason": config.get("reason", "Stopped by runbook")}, "stop"
    if action in {"core.condition", "core.validation"}:
        valid = compare(config["left"], config.get("operator", "eq"), config.get("right"))
        if action == "core.validation" and not valid:
            raise WorkflowValidationError("Validation predicate failed.")
        return {"valid": valid}, "true" if valid else "false"
    if action == "core.switch":
        cases = config["cases"]
        if not isinstance(cases, dict) or len(cases) > 100:
            raise WorkflowValidationError("Switch requires up to 100 labeled cases.")
        branch = next((str(label) for label, value in cases.items() if compare(config["value"], "eq", value)), "default")
        return {"value": config["value"], "case": branch}, branch
    items = config.get("items")
    if action in {"core.filter", "core.map", "core.for_each", "core.batch"}:
        if not isinstance(items, list) or len(items) > limit:
            raise WorkflowValidationError(f"Collection must be an array with at most {limit} items.")
        if action == "core.filter":
            return {"items": [item for item in items if compare(lookup(f"item.{config['path']}", {"item": item}), config.get("operator", "eq"), config["value"])]}, "default"
        if action in {"core.map", "core.for_each"}:
            return {"items": [resolve(config["template"], scope | {"item": item}) for item in items]}, "default"
        size = config["size"]
        if type(size) is not int or not 1 <= size <= 100:
            raise WorkflowValidationError("Batch size must be an integer between 1 and 100.")
        return {"batches": [items[i:i + size] for i in range(0, len(items), size)]}, "default"
    raise WorkflowValidationError(f"Unknown logic action: {action}.")
