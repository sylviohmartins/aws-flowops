"""Deterministic, human-readable runbook import/export for UI and future GitOps use."""

from __future__ import annotations

import json
from typing import Literal

import yaml

from flowops.core.migrations import migrate_definition
from flowops.core.security import reject_secrets
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook, new_id, utcnow

Format = Literal["yaml", "json"]


def export_runbook(book: Runbook, format: Format = "yaml") -> str:
    body = book.model_dump(mode="json")
    reject_secrets(body)
    if format == "json":
        return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if format == "yaml":
        return yaml.safe_dump(body, sort_keys=True, allow_unicode=True, width=100)
    raise WorkflowValidationError("Unsupported runbook export format.")


def import_runbook(
    content: str,
    *,
    owner: str,
    format: Format | None = None,
    preserve_identity: bool = False,
) -> Runbook:
    if not content.strip() or len(content.encode()) > 1_048_576:
        raise WorkflowValidationError("Runbook import must be between 1 byte and 1 MiB.")
    detected: Format = format or ("json" if content.lstrip().startswith("{") else "yaml")
    try:
        raw = json.loads(content) if detected == "json" else yaml.safe_load(content)
    except (ValueError, yaml.YAMLError) as exc:
        raise WorkflowValidationError("Runbook import is not valid YAML/JSON.") from exc
    if not isinstance(raw, dict):
        raise WorkflowValidationError("Runbook import must contain one object.")
    reject_secrets(raw)
    migrated = migrate_definition(raw)
    try:
        book = Runbook.model_validate(migrated)
    except ValueError as exc:
        raise WorkflowValidationError("Runbook import does not match the supported schema.") from exc
    if not preserve_identity:
        book.id = new_id()
        book.version = 0
        book.created_at = utcnow()
        book.updated_at = book.created_at
    book.owner = owner
    return book


def clone_runbook(book: Runbook, *, owner: str, suffix: str = "Copy") -> Runbook:
    cloned = book.model_copy(deep=True)
    cloned.id = new_id()
    cloned.name = f"{book.name} — {suffix}"[:160]
    cloned.owner = owner
    cloned.version = 0
    cloned.created_at = utcnow()
    cloned.updated_at = cloned.created_at
    return cloned
