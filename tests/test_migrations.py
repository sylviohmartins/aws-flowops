import pytest

from flowops.core.migrations import DefinitionMigrator
from flowops.domain.errors import WorkflowValidationError


def test_node_migration_must_be_explicit_and_advance_version() -> None:
    migrator = DefinitionMigrator()
    migrator.register(
        "legacy.action",
        0,
        lambda node: node | {"node_version": 1, "config": node.get("settings", {})},
    )
    raw = {
        "schema_version": 1,
        "nodes": [
            {
                "id": "legacy",
                "action": "legacy.action",
                "node_version": 0,
                "settings": {"value": 1},
            }
        ],
    }
    migrated = migrator.migrate(raw)
    assert migrated["nodes"][0]["node_version"] == 1
    assert migrated["nodes"][0]["config"] == {"value": 1}


def test_unknown_old_or_future_versions_fail_closed() -> None:
    migrator = DefinitionMigrator()
    with pytest.raises(WorkflowValidationError, match="No migration registered"):
        migrator.migrate(
            {
                "schema_version": 1,
                "nodes": [{"id": "old", "action": "legacy.action", "node_version": 0}],
            }
        )
    with pytest.raises(WorkflowValidationError, match="Unsupported node version"):
        migrator.migrate(
            {
                "schema_version": 1,
                "nodes": [{"id": "future", "action": "future.action", "node_version": 2}],
            }
        )
    with pytest.raises(WorkflowValidationError, match="Unsupported Runbook schema"):
        migrator.migrate({"schema_version": 2, "nodes": []})
