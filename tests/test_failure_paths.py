import tempfile
from pathlib import Path
from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.engine import Engine
from flowops.core.graph import validate_graph
from flowops.domain.errors import ProviderError, WorkflowValidationError
from flowops.domain.models import AWSContext, Edge, Identity, Node, Risk, Runbook, Status
from flowops.persistence.repository import Repository


class RecoverableAction:
    def __init__(self) -> None:
        self.metadata = Metadata(
            "test.recoverable",
            "test",
            "test",
            "recoverable",
            "Fails once so an explicit compensation node can recover the runbook.",
            risk=Risk.MEDIUM,
            read_only=False,
            idempotent=True,
        )
        self.calls = 0

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return {"simulation": True}

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("ExpectedFailure")
        return {"restored": True}


def failure_book() -> Runbook:
    return Runbook(
        name="Failure recovery",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="mutation", action="test.recoverable", failure_policy="FAIL_BRANCH"),
            Node(
                id="compensate",
                action="core.compensation",
                config={"action": "test.recoverable", "config": {}},
            ),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="mutation"),
            Edge(source="mutation", target="end"),
            Edge(source="mutation", target="compensate", branch="failure"),
            Edge(source="compensate", target="end"),
        ],
    )


def test_fail_branch_routes_to_explicit_compensation() -> None:
    with tempfile.TemporaryDirectory() as temp:
        repository = Repository(Path(temp) / "failure.db")
        registry = ActionRegistry()
        action = RecoverableAction()
        registry.register(action)
        engine = Engine(repository, registry)
        book = failure_book()
        revision = repository.save_draft(book, "author")
        published = repository.publish(book.id, "author", revision)
        execution = engine.submit(
            published,
            Identity(id="operator", roles=["ADMIN"]),
            AWSContext(),
            {},
            token="failure-branch",
            dry_run=False,
            reason="exercise recovery",
        )
        completed = engine.execute(execution.id)
        nodes = engine.store.nodes(execution.id)

        assert completed.status == Status.SUCCESS
        assert nodes["mutation"]["status"] == Status.FAILED
        assert nodes["mutation"]["branch"] == "failure"
        assert nodes["compensate"]["status"] == Status.SUCCESS
        assert action.calls == 2


def test_fail_branch_requires_an_explicit_failure_edge() -> None:
    registry = ActionRegistry()
    registry.register(RecoverableAction())
    book = failure_book()
    book.edges = [edge for edge in book.edges if edge.branch != "failure"]
    with pytest.raises(WorkflowValidationError, match="requires a failure edge"):
        validate_graph(book, registry)
