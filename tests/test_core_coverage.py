from __future__ import annotations

import logging
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

import pytest

from flowops.core.actions import ActionRegistry, Metadata
from flowops.core.expressions import compare, lookup, path_parts, references, resolve
from flowops.core.graph import bind_parameters, validate_graph
from flowops.core.logic import logic
from flowops.core.migrations import DefinitionMigrator, migrate_definition
from flowops.core.security import REDACTED, bounded_output, redact, reject_secrets
from flowops.core.worker import LocalWorker
from flowops.domain.errors import PolicyViolation, WorkflowValidationError
from flowops.domain.models import Edge, Execution, Identity, Node, Parameter, Runbook, Status
from flowops.observability import configure_logging, emit, metric_snapshot


@dataclass
class DummyAction:
    metadata: Metadata

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: Any) -> Any:
        return config

    def execute(self, config: dict[str, Any], context: Any) -> Any:
        return config


def simple_book() -> Runbook:
    return Runbook(
        name="coverage",
        parameters={
            "required": Parameter(type="string"),
            "optional": Parameter(type="integer", required=False, default=3),
        },
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="end")],
    )


def test_action_registry_duplicate_unknown_and_sorted_list() -> None:
    registry = ActionRegistry()
    b = DummyAction(Metadata("b", "test", "svc", "B", "b"))
    a = DummyAction(Metadata("a", "test", "svc", "A", "a"))
    registry.register(b)
    registry.register(a)
    assert registry.get("a") is a
    assert [item.id for item in registry.list()] == ["a", "b"]
    with pytest.raises(WorkflowValidationError, match="Duplicate action"):
        registry.register(a)
    with pytest.raises(WorkflowValidationError, match="Unknown action"):
        registry.get("missing")


def test_expression_path_lookup_and_redaction_guards() -> None:
    assert path_parts("params.a[2].b") == ["params", "a", 2, "b"]
    for invalid in ("", "1bad", "params[-1]", "params.a[]", "a" * 1025):
        with pytest.raises(WorkflowValidationError, match="Invalid data path"):
            path_parts(invalid)

    scope = {
        "params": {"items": [{"value": 9}], "secret": REDACTED, "cut": {"_truncated": True}},
        "nodes": {},
    }
    assert lookup("params.items[0].value", scope) == 9
    for bad in ("unknown.value", "params.items[2]", "params.items.value"):
        with pytest.raises(WorkflowValidationError):
            lookup(bad, scope)
    with pytest.raises(WorkflowValidationError, match="Redacted or truncated"):
        lookup("params.secret", scope)
    with pytest.raises(WorkflowValidationError, match="Redacted or truncated"):
        lookup("params.cut", scope)


def test_references_and_resolution_cover_all_shapes() -> None:
    value = {
        "a": "{{ params.name }}",
        "b": ["prefix-{{ context.region }}", 7],
    }
    assert references(value) == ["params.name", "context.region"]
    with pytest.raises(WorkflowValidationError, match="Malformed expression"):
        references("{{ params.name }")
    nested: Any = "leaf"
    for _ in range(34):
        nested = [nested]
    with pytest.raises(WorkflowValidationError, match="nesting exceeds"):
        references(nested)
    with pytest.raises(WorkflowValidationError, match="nesting exceeds"):
        resolve(nested, {})

    scope = {
        "params": {"name": "alice", "obj": {"x": 1}},
        "context": {"region": "sa-east-1"},
        "nodes": {},
        "input": {},
        "item": {},
    }
    assert resolve("{{ params.obj }}", scope) == {"x": 1}
    assert resolve("hello {{ params.name }}", scope) == "hello alice"
    assert resolve({"x": ["{{ params.name }}", 1]}, scope) == {"x": ["alice", 1]}
    assert resolve(5, scope) == 5
    with pytest.raises(WorkflowValidationError, match="structured values"):
        resolve("x={{ params.obj }}", scope)


def test_compare_full_predicate_vocabulary() -> None:
    assert compare(1, "eq", 1)
    assert not compare(True, "eq", 1)
    assert compare(1, "ne", 2)
    assert compare("x", "exists")
    assert not compare(None, "exists")
    assert compare([1], "truthy")
    assert compare(2, "gt", 1)
    assert compare(2, "gte", 2)
    assert compare(1, "lt", 2)
    assert compare(2, "lte", 2)
    assert compare("a", "in", ["a", "b"])
    assert compare("bc", "contains", "b")
    with pytest.raises(WorkflowValidationError, match="incompatible types"):
        compare(1, "gt", "x")
    with pytest.raises(WorkflowValidationError, match="Unknown predicate"):
        compare(1, "bogus", 1)


def test_logic_nodes_and_collection_contracts() -> None:
    for action in ("core.start", "core.end", "core.parallel"):
        assert logic(action, {"value": 3}, {}) == (3, "default")
    assert logic("core.merge", {}, {"input": {"x": 1}}) == ({"x": 1}, "default")
    assert logic("core.merge", {"inputs": {"y": 2}}, {}) == ({"y": 2}, "default")
    stopped, branch = logic("core.stop", {}, {})
    assert stopped == {"reason": "Stopped by runbook"}
    assert branch == "stop"

    assert logic("core.condition", {"left": 1, "operator": "eq", "right": 1}, {}) == (
        {"valid": True},
        "true",
    )
    assert logic("core.condition", {"left": 1, "operator": "eq", "right": 2}, {}) == (
        {"valid": False},
        "false",
    )
    with pytest.raises(WorkflowValidationError, match="Validation predicate failed"):
        logic("core.validation", {"left": False, "operator": "truthy"}, {})

    assert logic("core.switch", {"value": "b", "cases": {"A": "a", "B": "b"}}, {}) == (
        {"value": "b", "case": "B"},
        "B",
    )
    assert logic("core.switch", {"value": "x", "cases": {"A": "a"}}, {})[1] == "default"
    with pytest.raises(WorkflowValidationError, match="Switch requires"):
        logic("core.switch", {"value": "x", "cases": []}, {})
    with pytest.raises(WorkflowValidationError, match="Switch requires"):
        logic("core.switch", {"value": "x", "cases": {str(i): i for i in range(101)}}, {})

    items = [{"value": 1}, {"value": 2}, {"value": 1}]
    filtered, _ = logic(
        "core.filter",
        {"items": items, "path": "value", "value": 1, "operator": "eq"},
        {},
    )
    assert filtered["items"] == [items[0], items[2]]
    mapped, _ = logic(
        "core.map",
        {"items": items, "template": {"v": "{{ item.value }}"}},
        {},
    )
    assert mapped["items"] == [{"v": 1}, {"v": 2}, {"v": 1}]
    each, _ = logic(
        "core.for_each",
        {"items": items, "template": "{{ item.value }}"},
        {},
    )
    assert each["items"] == [1, 2, 1]
    batched, _ = logic("core.batch", {"items": [1, 2, 3], "size": 2}, {})
    assert batched["batches"] == [[1, 2], [3]]

    for invalid_items in ("not-list", list(range(1001))):
        with pytest.raises(WorkflowValidationError, match="Collection must be"):
            logic("core.map", {"items": invalid_items, "template": "x"}, {})
    for invalid_size in (True, 0, 101):
        with pytest.raises(WorkflowValidationError, match="Batch size"):
            logic("core.batch", {"items": [1], "size": invalid_size}, {})
    with pytest.raises(WorkflowValidationError, match="Unknown logic action"):
        logic("core.nope", {}, {})


def test_security_redaction_rejection_and_external_payload() -> None:
    assert redact({"password": "x", "safe": "AKIAABCDEFGHIJKLMNOP"}) == {
        "password": REDACTED,
        "safe": REDACTED,
    }
    assert redact(("Bearer abc.def", 1)) == ["Bearer [REDACTED]", 1]
    serialized = redact('{"authorization":"Bearer abc"}')
    assert isinstance(serialized, str)
    assert REDACTED in serialized
    assert redact(object()).endswith(" omitted]")

    deep: Any = "leaf"
    for _ in range(34):
        deep = {"x": deep}
    assert "_truncated" in str(redact(deep))

    reject_secrets({"safe": "value"})
    with pytest.raises(PolicyViolation, match="Sensitive literals"):
        reject_secrets({"clientToken": "secret"})

    class Store:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def put(self, key: str, payload: bytes) -> str:
            self.calls.append((key, payload))
            return "blob://1"

    assert bounded_output({"a": 1}, limit=100) == {"a": 1}
    store = Store()
    result = bounded_output({"value": "x" * 100}, limit=10, store=store, key="run/node")
    assert result["_truncated"] is True
    assert result["external_reference"] == "blob://1"
    assert store.calls[0][0] == "run/node"


def test_definition_migrator_success_and_fail_closed_branches() -> None:
    migrator = DefinitionMigrator()

    def advance(node: dict[str, Any]) -> dict[str, Any]:
        node["node_version"] = 1
        node["config"] = {"migrated": True}
        return node

    migrator.register("test.action", 0, advance)
    migrated = migrator.migrate(
        {"schema_version": 1, "nodes": [{"id": "n", "action": "test.action", "node_version": 0}]}
    )
    assert migrated["nodes"][0]["node_version"] == 1
    assert migrated["nodes"][0]["config"] == {"migrated": True}

    with pytest.raises(WorkflowValidationError, match="Duplicate node migration"):
        migrator.register("test.action", 0, advance)
    for version in (-1, 1):
        with pytest.raises(WorkflowValidationError, match="must advance an older"):
            DefinitionMigrator().register("x", version, advance)

    invalids = [
        ({"schema_version": 2, "nodes": []}, "Unsupported Runbook schema"),
        ({"nodes": {}}, "nodes must be an array"),
        ({"nodes": ["bad"]}, "must be an object"),
        ({"nodes": [{}]}, "action is required"),
        ({"nodes": [{"action": "a", "node_version": -1}]}, "non-negative integer"),
        ({"nodes": [{"action": "a", "node_version": 2}]}, "Unsupported node version"),
        ({"nodes": [{"action": "a", "node_version": 0}]}, "No migration registered"),
    ]
    for raw, message in invalids:
        with pytest.raises(WorkflowValidationError, match=message):
            DefinitionMigrator().migrate(raw)

    broken = DefinitionMigrator()
    broken.register("a", 0, lambda node: node)
    with pytest.raises(WorkflowValidationError, match="did not advance"):
        broken.migrate({"nodes": [{"action": "a", "node_version": 0}]})

    original = {"nodes": [{"action": "core.start"}]}
    result = migrate_definition(original)
    assert result is not original
    assert result["schema_version"] == 1
    assert result["nodes"][0]["node_version"] == 1


def test_bind_parameters_defaults_and_validation() -> None:
    book = simple_book()
    assert bind_parameters(book, {"required": "ok"}) == {"required": "ok", "optional": 3}
    with pytest.raises(WorkflowValidationError, match="Unknown runbook parameter"):
        bind_parameters(book, {"required": "ok", "extra": 1})
    with pytest.raises(WorkflowValidationError, match="Required parameter"):
        bind_parameters(book, {})
    with pytest.raises(WorkflowValidationError, match="must be string"):
        bind_parameters(book, {"required": 1})

    optional_none = Runbook(
        name="optional",
        parameters={"x": Parameter(type="string", required=False)},
        nodes=[Node(id="start", action="core.start"), Node(id="end", action="core.end")],
        edges=[Edge(source="start", target="end")],
    )
    assert bind_parameters(optional_none, {}) == {"x": None}


def test_validate_graph_basic_guardrails() -> None:
    assert validate_graph(simple_book()) == ["start", "end"]
    with pytest.raises(WorkflowValidationError, match="1–200 nodes"):
        validate_graph(Runbook(name="empty"))

    duplicate = simple_book()
    duplicate.nodes.append(Node(id="end", action="core.end"))
    with pytest.raises(WorkflowValidationError, match="Node IDs must be unique"):
        validate_graph(duplicate)

    no_end = Runbook(name="no-end", nodes=[Node(id="start", action="core.start")])
    with pytest.raises(WorkflowValidationError, match="exactly one Start"):
        validate_graph(no_end)

    unknown_edge = simple_book()
    unknown_edge.edges = [Edge(source="start", target="missing")]
    with pytest.raises(WorkflowValidationError, match="unknown node"):
        validate_graph(unknown_edge)

    duplicate_edge = simple_book()
    duplicate_edge.edges.append(Edge(source="start", target="end"))
    with pytest.raises(WorkflowValidationError, match="Duplicate edge"):
        validate_graph(duplicate_edge)

    bad_branch = simple_book()
    bad_branch.edges = [Edge(source="start", target="end", branch="true")]
    with pytest.raises(WorkflowValidationError, match="Invalid branch"):
        validate_graph(bad_branch)

    cycle = Runbook(
        name="cycle",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="middle", action="core.parallel"),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="middle"),
            Edge(source="middle", target="end"),
            Edge(source="middle", target="start"),
        ],
    )
    with pytest.raises(WorkflowValidationError):
        validate_graph(cycle)


def test_observability_logging_duration_and_node_metrics(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("flowops")
    logger.handlers.clear()
    monkeypatch.setenv("FLOWOPS_LOG_LEVEL", "DEBUG")
    assert configure_logging().level == logging.DEBUG
    assert len(configure_logging("NOT_A_LEVEL").handlers) == 1

    caplog.set_level(logging.INFO, logger="flowops")
    emit("TEST", password="secret", safe="ok")

    book = Runbook(
        name="metrics",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="aws", action="sqs.send_message"),
            Node(id="end", action="core.end"),
        ],
        edges=[Edge(source="start", target="aws"), Edge(source="aws", target="end")],
    )
    actor = Identity(id="u")
    successful = Execution(
        runbook_id=book.id,
        runbook_version=1,
        snapshot=book,
        snapshot_hash="h",
        actor=actor,
        aws_context={"environment": "dev"},
        status=Status.SUCCESS,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:02.500000+00:00",
    )
    failed = successful.model_copy(deep=True)
    failed.id = "failed"
    failed.status = Status.FAILED
    failed.started_at = "bad"
    failed.finished_at = "also-bad"
    pending = successful.model_copy(deep=True)
    pending.id = "pending"
    pending.started_at = None
    pending.finished_at = None

    metrics = metric_snapshot(
        [successful, failed, pending],
        {
            successful.id: {
                "start": {"status": Status.SUCCESS},
                "aws": {"status": Status.FAILED},
                "aws__1": {"status": Status.SUCCESS},
            }
        },
    )
    assert metrics == {
        "runbook_executions_total": 3,
        "runbook_failures_total": 1,
        "runbook_duration_seconds_total": 2.5,
        "node_executions_total": 3,
        "node_failures_total": 1,
        "aws_api_calls_total": 2,
    }


class FakeStore:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def history(self, limit: int) -> list[Any]:
        assert limit == 2000
        return self.rows


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.store = FakeStore([])

    def execute(self, execution_id: str) -> Any:
        self.calls.append(execution_id)
        return execution_id


def test_local_worker_deduplicates_dispatches_and_calls_release() -> None:
    engine = FakeEngine()
    released: list[str] = []
    worker = LocalWorker(engine, workers=99, on_done=released.append)  # type: ignore[arg-type]
    try:
        first = worker.enqueue("a")
        second = worker.enqueue("a")
        assert isinstance(first, Future)
        assert second is first or second.result() == "a"
        assert first.result() == "a"
        worker.enqueue("a").result()
        assert released.count("a") >= 1

        pending = type("Row", (), {"id": "p", "status": Status.PENDING})()
        done = type("Row", (), {"id": "s", "status": Status.SUCCESS})()
        engine.store.rows = [pending, done]
        worker.dispatch_pending()
        worker.futures["p"].result()
        assert "p" in engine.calls
    finally:
        worker.close()
