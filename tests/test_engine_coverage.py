from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.engine import Engine
from flowops.domain.errors import (
    AuthorizationError,
    ConflictError,
    PolicyViolation,
    ProviderError,
    WorkflowValidationError,
)
from flowops.domain.models import AWSContext, Edge, Identity, Node, Risk, Runbook, Status
from flowops.persistence.repository import Repository


class RecordingAction:
    def __init__(
        self,
        action_id: str = "test.action",
        *,
        read_only: bool = True,
        idempotent: bool = True,
        validation_error: Exception | None = None,
    ) -> None:
        self.metadata = Metadata(
            action_id,
            "test",
            "test",
            action_id.split(".")[-1],
            "Coverage action",
            risk=Risk.READ_ONLY if read_only else Risk.HIGH,
            read_only=read_only,
            idempotent=idempotent,
        )
        self.validation_error = validation_error
        self.calls: list[dict[str, Any]] = []

    def validate(self, config: dict[str, Any]) -> None:
        if self.validation_error is not None:
            raise self.validation_error

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return {"preview": config}

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        self.calls.append(config)
        return {"config": config, "node": context.node_id}


def runtime(tmp_path: Path, *actions: RecordingAction) -> tuple[Repository, ActionRegistry, Engine]:
    repository = Repository(tmp_path / "engine-coverage.db")
    registry = ActionRegistry()
    for action in actions:
        registry.register(action)
    return repository, registry, Engine(repository, registry, max_parallel=20)


def publish(repository: Repository, book: Runbook) -> Runbook:
    revision = repository.save_draft(book, "author")
    return repository.publish(book.id, "author", revision)


def linear_book(*middle: Node) -> Runbook:
    nodes = [Node(id="start", action="core.start"), *middle, Node(id="end", action="core.end")]
    return Runbook(
        name="Engine coverage",
        environments=["dev"],
        nodes=nodes,
        edges=[Edge(source=a.id, target=b.id) for a, b in zip(nodes, nodes[1:], strict=False)],
    )


def submit(
    engine: Engine,
    book: Runbook,
    *,
    token: str = "token",
    dry_run: bool = True,
    correlation: dict[str, str] | None = None,
) -> str:
    return engine.submit(
        book,
        Identity(id="operator", roles=["ADMIN"]),
        AWSContext(),
        {},
        token=token,
        dry_run=dry_run,
        reason="coverage",
        correlation_context=correlation,
    ).id


def test_submit_rejects_changed_archived_invalid_correlation_and_tokens(tmp_path: Path) -> None:
    repository, _, engine = runtime(tmp_path)
    book = publish(repository, linear_book())

    changed = book.model_copy(deep=True)
    changed.description = "changed after publication"
    with pytest.raises(ConflictError, match="unchanged published version"):
        submit(engine, changed)

    invalid_correlations = [
        {str(index): "v" for index in range(21)},
        {"": "value"},
        {"key": "x" * 501},
    ]
    for index, correlation in enumerate(invalid_correlations):
        with pytest.raises(WorkflowValidationError, match="Correlation context"):
            submit(engine, book, token=f"correlation-{index}", correlation=correlation)

    for token in ("", "x" * 201):
        with pytest.raises(WorkflowValidationError, match="submission token"):
            submit(engine, book, token=token)

    repository.archive(book.id, "author")
    with pytest.raises(PolicyViolation, match="Archived runbooks"):
        submit(engine, book, token="archived")


def test_approval_reason_authorization_rejection_and_dry_run(tmp_path: Path) -> None:
    repository, _, engine = runtime(tmp_path)
    book = publish(repository, linear_book(Node(id="approval", action="core.approval")))

    simulated = engine.execute(submit(engine, book, token="simulation", dry_run=True))
    assert simulated.status == Status.SUCCESS
    assert simulated.node_outputs["approval"]["approval_required_live"] is True
    assert engine.store.pending_approvals() == []

    execution_id = submit(engine, book, token="live", dry_run=False)
    waiting = engine.execute(execution_id)
    assert waiting.status == Status.WAITING_APPROVAL
    approval = engine.store.pending_approvals()[0]
    approval_digest = approval["digest"]

    with pytest.raises(AuthorizationError):
        engine.approve(
            execution_id,
            "approval",
            approval_digest,
            Identity(id="viewer", roles=["VIEWER"]),
            approved=True,
            reason="reviewed",
        )
    with pytest.raises(PolicyViolation, match="reason is required"):
        engine.approve(
            execution_id,
            "approval",
            approval_digest,
            Identity(id="approver", roles=["APPROVER"]),
            approved=True,
            reason="   ",
        )

    engine.approve(
        execution_id,
        "approval",
        approval_digest,
        Identity(id="approver", roles=["APPROVER"]),
        approved=False,
        reason="rejected after review",
    )
    assert engine.store.get(execution_id).status == Status.CANCELLED


def test_interrupted_checkpoint_fails_closed_and_cancel_flag_stops_before_nodes(
    tmp_path: Path,
) -> None:
    repository, _, engine = runtime(tmp_path)
    book = publish(repository, linear_book())

    interrupted_id = submit(engine, book, token="interrupted")
    interrupted = engine.store.get(interrupted_id)
    engine.store.checkpoint(interrupted, "start", Status.RUNNING, {"attempts": 1})
    result = engine.execute(interrupted_id)
    assert result.status == Status.FAILED
    assert "uncertain outcome" in (result.error or "")

    cancelled_id = submit(engine, book, token="cancel-flag")
    with repository.transaction() as db:
        db.execute("UPDATE executions SET cancel_requested=1 WHERE id=?", (cancelled_id,))
    cancelled = engine.execute(cancelled_id)
    assert cancelled.status == Status.CANCELLED
    assert set(engine.store.nodes(cancelled_id)) == {"start", "end"}
    assert all(
        detail["status"] == Status.SKIPPED for detail in engine.store.nodes(cancelled_id).values()
    )


def test_parallel_read_nodes_disabled_node_and_stop_branch(tmp_path: Path) -> None:
    action = RecordingAction("test.read", read_only=True)
    repository, _, engine = runtime(tmp_path, action)
    parallel = Runbook(
        name="Parallel reads",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="left", action="test.read", config={"side": "left"}),
            Node(id="right", action="test.read", config={"side": "right"}),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="left"),
            Edge(source="start", target="right"),
            Edge(source="left", target="end"),
            Edge(source="right", target="end"),
        ],
    )
    completed = engine.execute(submit(engine, publish(repository, parallel), token="parallel"))
    assert completed.status == Status.SUCCESS
    assert sorted(call["side"] for call in action.calls) == ["left", "right"]
    assert engine.max_parallel == 8

    disabled = publish(
        repository,
        linear_book(Node(id="disabled", action="test.read", enabled=False)),
    )
    completed = engine.execute(submit(engine, disabled, token="disabled"))
    assert completed.node_outputs["disabled"] == {"disabled": True}
    assert len(action.calls) == 2

    stopped = publish(
        repository,
        Runbook(
            name="Explicit stop",
            environments=["dev"],
            nodes=[
                Node(id="start", action="core.start"),
                Node(id="stop", action="core.stop", config={"reason": "operator stop"}),
            ],
            edges=[Edge(source="start", target="stop")],
        ),
    )
    result = engine.execute(submit(engine, stopped, token="stop"))
    assert result.status == Status.CANCELLED
    assert engine.store.nodes(result.id)["stop"]["status"] == Status.SUCCESS


def test_wait_retry_for_each_and_continue_failure_paths(tmp_path: Path) -> None:
    action = RecordingAction("test.read", read_only=True)
    repository, _, engine = runtime(tmp_path, action)

    workflow = publish(
        repository,
        linear_book(
            Node(id="wait", action="core.wait", config={"seconds": 2}),
            Node(
                id="retry",
                action="core.retry",
                config={"action": "test.read", "config": {"kind": "retry"}},
            ),
            Node(
                id="each",
                action="core.for_each",
                config={
                    "items": [{"value": 1}, {"value": 2}],
                    "template": {"value": "{{ item.value }}"},
                    "action": "test.read",
                },
            ),
        ),
    )
    completed = engine.execute(submit(engine, workflow, token="composed", dry_run=True))
    assert completed.status == Status.SUCCESS
    assert completed.node_outputs["wait"] == {"waited_seconds": 0}
    assert completed.node_outputs["each"]["items"][0]["config"] == {"value": 1}
    assert len(action.calls) == 3

    invalid_wait = publish(
        repository,
        linear_book(
            Node(
                id="wait_bad",
                action="core.wait",
                config={"seconds": 4000},
                failure_policy="CONTINUE",
            )
        ),
    )
    continued = engine.execute(submit(engine, invalid_wait, token="continue"))
    assert continued.status == Status.SUCCESS
    assert continued.node_outputs["wait_bad"]["failed"] is True


def test_unexpected_action_input_is_sanitized_into_failed_outcome(tmp_path: Path) -> None:
    broken = RecordingAction(
        "test.broken", validation_error=ValueError("raw implementation detail")
    )
    repository, _, engine = runtime(tmp_path, broken)
    book = publish(repository, linear_book(Node(id="broken", action="test.broken")))
    result = engine.execute(submit(engine, book, token="unexpected"))
    assert result.status == Status.FAILED
    assert result.error == "Invalid action input or unexpected provider failure."
    assert "raw implementation detail" not in result.model_dump_json()


def test_private_approval_rejected_decision_and_provider_retry_error(tmp_path: Path) -> None:
    action = RecordingAction("test.retry", read_only=True, idempotent=True)
    repository, _, engine = runtime(tmp_path, action)
    book = publish(repository, linear_book(Node(id="approval", action="core.approval")))
    execution_id = submit(engine, book, token="private-approval", dry_run=False)
    execution = engine.store.get(execution_id)
    node = next(node for node in book.nodes if node.id == "approval")

    original = engine.store.approval
    engine.store.approval = lambda *args, **kwargs: "REJECTED"  # type: ignore[method-assign]
    try:
        with pytest.raises(PolicyViolation, match="approval was rejected"):
            engine._approval(execution, node, {}, {"preview": True})
    finally:
        engine.store.approval = original  # type: ignore[method-assign]

    class RetryFailure(RecordingAction):
        def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
            raise ProviderError("NotRetryable", retryable=False)

    failing = RetryFailure("test.failure", read_only=True, idempotent=True)
    registry = ActionRegistry()
    registry.register(failing)
    isolated = Engine(repository, registry)
    failed_book = publish(
        repository,
        linear_book(Node(id="failure", action="test.failure")),
    )
    failed = isolated.execute(submit(isolated, failed_book, token="provider-error"))
    assert failed.status == Status.FAILED
    assert failed.error == "NotRetryable"
