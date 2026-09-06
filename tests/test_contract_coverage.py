from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flowops.application import FlowOpsRuntime
from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.graph import bind_parameters, validate_graph
from flowops.core.policies import PolicyEngine, permissions, require
from flowops.core.serialization import export_runbook, import_runbook
from flowops.domain.errors import AuthorizationError, PolicyViolation, WorkflowValidationError
from flowops.domain.models import (
    AWSContext,
    Edge,
    Execution,
    Identity,
    Node,
    Parameter,
    Risk,
    Runbook,
)
from flowops.persistence.repository import Repository


class FakeAction:
    def __init__(self, metadata: Metadata) -> None:
        self.metadata = metadata

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config


def registry() -> ActionRegistry:
    result = ActionRegistry()
    result.register(
        FakeAction(
            Metadata(
                "fake.read",
                "fake",
                "fake",
                "read",
                "read",
                read_only=True,
                input_schema={"type": "object", "required": ["Name"]},
            )
        )
    )
    result.register(
        FakeAction(
            Metadata(
                "fake.write",
                "fake",
                "fake",
                "write",
                "write",
                risk=Risk.MEDIUM,
                read_only=False,
            )
        )
    )
    return result


def basic_book() -> Runbook:
    return Runbook(
        name="contract",
        team="team-a",
        environments={"dev", "production"},
        parameters={"name": Parameter(type="string")},
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="end")],
    )


def operator() -> Identity:
    return Identity(
        id="operator",
        roles={"OPERATOR"},
        permissions={"runbook.execute.production", "aws.destructive"},
        teams={"team-a"},
    )


def execution(
    *,
    environment: str = "dev",
    dry_run: bool = False,
    reason: str = "change-1",
    actor: Identity | None = None,
    book: Runbook | None = None,
) -> Execution:
    runbook = book or basic_book()
    return Execution(
        runbook_id=runbook.id,
        runbook_version=1,
        snapshot=runbook,
        snapshot_hash="digest",
        actor=actor or operator(),
        aws_context=AWSContext(environment=environment),
        dry_run=dry_run,
        reason=reason,
    )


def test_graph_start_end_failure_required_and_nested_action_guards() -> None:
    bad_start = Runbook(
        name="bad start",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="read", action="fake.read", config={"Name": "x"}),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="read", target="start"),
            Edge(source="start", target="end"),
        ],
    )
    with pytest.raises(WorkflowValidationError, match="Start has no input"):
        validate_graph(bad_start, registry())

    bad_end = Runbook(
        name="bad end",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="end", action="core.end"),
            Node(id="other", action="core.stop"),
        ],
        edges=[Edge(source="start", target="end"), Edge(source="end", target="other")],
    )
    with pytest.raises(WorkflowValidationError, match="End/Stop has no output"):
        validate_graph(bad_end)

    failure = Runbook(
        name="failure",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="write", action="fake.write", failure_policy="FAIL_BRANCH"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="write"), Edge(source="write", target="end")],
    )
    with pytest.raises(WorkflowValidationError, match="requires a failure edge"):
        validate_graph(failure, registry())

    missing_required = Runbook(
        name="required",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="read", action="fake.read"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="read"), Edge(source="read", target="end")],
    )
    with pytest.raises(WorkflowValidationError, match="required input Name"):
        validate_graph(missing_required, registry())

    bad_nested = Runbook(
        name="nested",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="retry", action="core.retry", config={"action": 7, "config": {}}),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="retry"), Edge(source="retry", target="end")],
    )
    with pytest.raises(WorkflowValidationError, match="nested action must be a string"):
        validate_graph(bad_nested, registry())

    unknown_nested = bad_nested.model_copy(deep=True)
    retry = next(node for node in unknown_nested.nodes if node.id == "retry")
    retry.config["action"] = "fake.missing"
    with pytest.raises(WorkflowValidationError, match="Unknown action"):
        validate_graph(unknown_nested, registry())


def test_graph_switch_failure_expression_and_connectivity_guards() -> None:
    switch = Runbook(
        name="switch",
        parameters={"name": Parameter(type="string")},
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="choice", action="core.switch", config={"value": "x", "cases": {"A": "a"}}),
            Node(id="a", action="core.end"),
            Node(id="default", action="core.stop"),
        ],
        edges=[
            Edge(source="start", target="choice"),
            Edge(source="choice", target="a", branch="A"),
            Edge(source="choice", target="default", branch="default"),
        ],
    )
    assert validate_graph(switch) == ["start", "choice", "a", "default"]

    disconnected = basic_book()
    disconnected.nodes.append(Node(id="lonely", action="core.stop"))
    with pytest.raises(WorkflowValidationError, match="Disconnected node"):
        validate_graph(disconnected)

    dead_end = Runbook(
        name="dead",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="middle", action="core.parallel"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="middle"), Edge(source="start", target="end")],
    )
    with pytest.raises(WorkflowValidationError, match="Connect middle"):
        validate_graph(dead_end)

    invalid_refs = [
        ("{{ nodes.end.output }}", "output reference must target an ancestor"),
        ("{{ params.missing }}", "parameter does not exist"),
        ("{{ item.value }}", "item references are limited"),
        ("{{ mystery.value }}", "Unknown expression root"),
    ]
    for ref, message in invalid_refs:
        book = Runbook(
            name="refs",
            nodes=[
                Node(id="start", action="core.start"),
                Node(id="middle", action="core.parallel", config={"value": ref}),
                Node(id="end", action="core.end"),
            ],
            edges=[Edge(source="start", target="middle"), Edge(source="middle", target="end")],
        )
        with pytest.raises(WorkflowValidationError, match=message):
            validate_graph(book)

    valid_item = Runbook(
        name="item",
        nodes=[
            Node(id="start", action="core.start"),
            Node(
                id="map",
                action="core.map",
                config={"items": [], "template": "{{ item.value }}"},
            ),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="map"), Edge(source="map", target="end")],
    )
    validate_graph(valid_item)


def test_bind_parameters_accepts_every_supported_type() -> None:
    book = Runbook(
        name="types",
        parameters={
            "s": Parameter(type="string"),
            "i": Parameter(type="integer"),
            "n": Parameter(type="number"),
            "b": Parameter(type="boolean"),
            "a": Parameter(type="array"),
            "o": Parameter(type="object"),
        },
        nodes=[Node(id="start", action="core.start"), Node(id="end", action="core.end")],
        edges=[Edge(source="start", target="end")],
    )
    supplied = {"s": "x", "i": 1, "n": 1.5, "b": True, "a": [1], "o": {"x": 1}}
    assert bind_parameters(book, supplied) == supplied
    with pytest.raises(WorkflowValidationError, match="must be integer"):
        bind_parameters(book, supplied | {"i": True})


def test_serialization_rejects_invalid_formats_sizes_shapes_and_schema() -> None:
    book = basic_book()
    with pytest.raises(WorkflowValidationError, match="Unsupported runbook export format"):
        export_runbook(book, "toml")  # type: ignore[arg-type]

    for content in ("", "   ", "x" * 1_048_577):
        with pytest.raises(WorkflowValidationError, match="between 1 byte and 1 MiB"):
            import_runbook(content, owner="u")

    with pytest.raises(WorkflowValidationError, match="valid YAML/JSON"):
        import_runbook("{invalid", owner="u", format="json")
    with pytest.raises(WorkflowValidationError, match="contain one object"):
        import_runbook("- one\n- two\n", owner="u", format="yaml")
    with pytest.raises(WorkflowValidationError, match="supported schema"):
        import_runbook(
            json.dumps(
                {
                    "name": "bad",
                    "nodes": [{"action": "core.start", "node_version": 1}],
                    "edges": "bad",
                }
            ),
            owner="u",
            format="json",
        )


def test_serialization_preserves_identity_only_when_explicit() -> None:
    source = basic_book()
    source.version = 7
    body = export_runbook(source, "json")
    preserved = import_runbook(body, owner="new", format="json", preserve_identity=True)
    assert preserved.id == source.id
    assert preserved.version == 7
    assert preserved.owner == "new"


def test_permissions_require_and_policy_fail_closed_paths() -> None:
    user = Identity(id="u", roles={"UNKNOWN"}, teams={"team-a"})
    assert permissions(user) == set()
    with pytest.raises(AuthorizationError, match="Permission required"):
        require(user, "runbook.read", basic_book())

    reader = Identity(id="r", roles={"VIEWER"}, teams={"other"})
    with pytest.raises(AuthorizationError, match="different team"):
        require(reader, "runbook.read", basic_book())

    engine = PolicyEngine(max_affected=2, approval_threshold=1)
    restricted = basic_book()
    restricted.environments = {"production"}
    with pytest.raises(PolicyViolation, match="not allowed"):
        engine.execution(execution(book=restricted, environment="dev"))
    with pytest.raises(PolicyViolation, match="change reason"):
        engine.execution(execution(environment="production", reason=" "))

    core = Metadata("core.test", "core", "core", "test", "test")
    assert engine.action(execution(), core) is False

    read = Metadata("fake.read", "fake", "fake", "read", "read", read_only=True)
    assert engine.action(execution(), read) is False
    write = Metadata(
        "w",
        "fake",
        "f",
        "w",
        "w",
        risk=Risk.MEDIUM,
        read_only=False,
    )
    assert engine.action(execution(dry_run=True), write) is False
    assert engine.action(execution(), write, affected=2) is True
    with pytest.raises(PolicyViolation, match="Affected-record limit"):
        engine.action(execution(), write, affected=3)


def test_runtime_rejects_untrusted_contexts_bad_allowlist_and_wires_release() -> None:
    with tempfile.TemporaryDirectory() as temp:
        repo = Repository(Path(temp) / "runtime.db")
        with pytest.raises(ValueError, match="Trusted AWS contexts"):
            FlowOpsRuntime.aws(repo, [])
        with pytest.raises(ValueError, match="Trusted AWS contexts"):
            FlowOpsRuntime.aws(repo, [AWSContext(mode="demo")])
        with pytest.raises(ValueError, match="service.operation"):
            FlowOpsRuntime.aws(repo, [AWSContext(mode="aws")], generic_allowlist={"invalid"})

        released: list[str] = []

        class Backend:
            def release(self, execution_id: str) -> None:
                released.append(execution_id)

        runtime = FlowOpsRuntime.from_registry(repo, ActionRegistry(), backend=Backend())
        runtime.close()
        runtime_without_release = FlowOpsRuntime.from_registry(
            repo, ActionRegistry(), backend=object()
        )
        runtime_without_release.close()
