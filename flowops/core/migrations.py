"""Explicit, deterministic migrations for serialized Runbook and Node definitions."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from flowops.domain.errors import WorkflowValidationError

CURRENT_RUNBOOK_SCHEMA = 1
CURRENT_NODE_VERSION = 1
NodeMigration = Callable[[dict[str, Any]], dict[str, Any]]


class DefinitionMigrator:
    """Migrate drafts before Pydantic validation without reinterpreting published snapshots."""

    def __init__(self) -> None:
        self._node_migrations: dict[tuple[str, int], NodeMigration] = {}

    def register(self, action: str, from_version: int, migration: NodeMigration) -> None:
        key = (action, from_version)
        if key in self._node_migrations:
            raise WorkflowValidationError(f"Duplicate node migration for {action} v{from_version}.")
        if from_version < 0 or from_version >= CURRENT_NODE_VERSION:
            raise WorkflowValidationError("Node migrations must advance an older version.")
        self._node_migrations[key] = migration

    def migrate(self, raw: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(raw)
        schema_version = result.get("schema_version", CURRENT_RUNBOOK_SCHEMA)
        if schema_version != CURRENT_RUNBOOK_SCHEMA:
            raise WorkflowValidationError(
                f"Unsupported Runbook schema version {schema_version}; expected {CURRENT_RUNBOOK_SCHEMA}."
            )
        result["schema_version"] = CURRENT_RUNBOOK_SCHEMA
        nodes = result.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("Runbook nodes must be an array.")
        migrated_nodes: list[dict[str, Any]] = []
        for value in nodes:
            if not isinstance(value, dict):
                raise WorkflowValidationError("Each serialized node must be an object.")
            node = copy.deepcopy(value)
            action = node.get("action")
            if not isinstance(action, str) or not action:
                raise WorkflowValidationError("Serialized node action is required.")
            version = node.get("node_version", CURRENT_NODE_VERSION)
            if type(version) is not int or version < 0:
                raise WorkflowValidationError("Node version must be a non-negative integer.")
            if version > CURRENT_NODE_VERSION:
                raise WorkflowValidationError(
                    f"Unsupported node version {version} for {action}; runtime supports v{CURRENT_NODE_VERSION}."
                )
            while version < CURRENT_NODE_VERSION:
                migration = self._node_migrations.get((action, version))
                if migration is None:
                    raise WorkflowValidationError(
                        f"No migration registered for {action} v{version}."
                    )
                node = migration(copy.deepcopy(node))
                next_version = node.get("node_version")
                if type(next_version) is not int or next_version <= version:
                    raise WorkflowValidationError(
                        f"Migration for {action} v{version} did not advance node_version."
                    )
                version = next_version
            node["node_version"] = CURRENT_NODE_VERSION
            migrated_nodes.append(node)
        result["nodes"] = migrated_nodes
        return result


DEFAULT_MIGRATOR = DefinitionMigrator()


def migrate_definition(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate an imported draft using only explicitly registered transformations."""
    return DEFAULT_MIGRATOR.migrate(raw)
