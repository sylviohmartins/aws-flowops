"""Structured, sanitized logging and in-process metric snapshots.

The module intentionally depends only on domain models and persisted node details. Hosts can
forward JSON logs to CloudWatch, OpenTelemetry collectors, Datadog, or another platform without
making the core depend on a vendor SDK.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Iterable

from flowops.core.security import bounded_output
from flowops.domain.models import Execution, Status

LOGGER_NAME = "flowops"


def configure_logging(level: str | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    configured = (level or os.getenv("FLOWOPS_LOG_LEVEL") or "INFO").upper()
    logger.setLevel(getattr(logging, configured, logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def emit(event: str, **fields: Any) -> None:
    """Emit one bounded JSON event without credentials or secret-shaped values."""
    payload = bounded_output({"event": event, **fields}, limit=65536)
    configure_logging().info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _duration_seconds(execution: Execution) -> float:
    if not execution.started_at or not execution.finished_at:
        return 0.0
    try:
        return max(
            0.0,
            (
                datetime.fromisoformat(execution.finished_at)
                - datetime.fromisoformat(execution.started_at)
            ).total_seconds(),
        )
    except ValueError:
        return 0.0


def metric_snapshot(
    executions: Iterable[Execution],
    node_details: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, float | int]:
    """Return the canonical FlowOps metric names from durable execution state."""
    rows = list(executions)
    nodes = node_details or {}
    failures = sum(execution.status == Status.FAILED for execution in rows)
    duration = sum(_duration_seconds(execution) for execution in rows)
    node_total = 0
    node_failures = 0
    aws_calls = 0
    for execution in rows:
        actions = {node.id: node.action for node in execution.snapshot.nodes}
        for node_id, detail in nodes.get(execution.id, {}).items():
            if "__" in node_id and node_id.split("__", 1)[0] in actions:
                action = actions[node_id.split("__", 1)[0]]
            else:
                action = actions.get(node_id, "")
            node_total += 1
            node_failures += detail.get("status") == Status.FAILED
            aws_calls += bool(action and not action.startswith("core."))
    return {
        "runbook_executions_total": len(rows),
        "runbook_failures_total": failures,
        "runbook_duration_seconds_total": round(duration, 6),
        "node_executions_total": node_total,
        "node_failures_total": node_failures,
        "aws_api_calls_total": aws_calls,
    }
