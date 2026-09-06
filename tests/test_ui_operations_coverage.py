from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.domain.models import AWSContext, Identity, Runbook, Status
from flowops.streamlit.ui import FlowOpsUI


class ButtonColumn:
    def __init__(self, clicks: set[str]) -> None:
        self.clicks = clicks

    def button(self, label: str, **kwargs: Any) -> bool:
        return label in self.clicks


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.select_values: dict[str, Any] = {}
        self.text_values: dict[str, str] = {}
        self.clicks: set[str] = set()
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.frames: list[Any] = []
        self.json_values: list[Any] = []
        self.rerun_called = False

    def header(self, value: str) -> None:
        return None

    def subheader(self, value: str) -> None:
        return None

    def info(self, value: str) -> None:
        self.infos.append(value)

    def warning(self, value: str) -> None:
        self.warnings.append(value)

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def dataframe(self, rows: Any, **kwargs: Any) -> None:
        self.frames.append(rows)

    def json(self, value: Any, **kwargs: Any) -> None:
        self.json_values.append(value)

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        chosen = self.select_values.get(label)
        return chosen if chosen in options else options[0]

    def text_input(self, label: str, **kwargs: Any) -> str:
        return self.text_values.get(label, "")

    def columns(self, count: int) -> list[ButtonColumn]:
        return [ButtonColumn(self.clicks) for _ in range(count)]

    def button(self, label: str, **kwargs: Any) -> bool:
        return label in self.clicks

    def rerun(self) -> None:
        self.rerun_called = True


def execution(status: Status, *, execution_id: str = "execution-1") -> Any:
    book = Runbook(name="Runbook", team="ops", version=1)
    return SimpleNamespace(
        id=execution_id,
        snapshot=book,
        runbook_version=1,
        actor=Identity(id="requester"),
        aws_context=AWSContext(environment="dev", account_id="123456789012", region="us-east-1"),
        started_at=None,
        created_at="2026-09-06",
        finished_at=None,
        status=status,
        reason="change",
        dry_run=True,
        error=None,
        parameters={"id": "42"},
    )


def presenter(fake: FakeStreamlit, monkeypatch: pytest.MonkeyPatch) -> FlowOpsUI:
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    ui = FlowOpsUI.__new__(FlowOpsUI)
    ui.user = Identity(id="operator", roles=["ADMIN"])
    ui.aws = AWSContext()
    return ui


def test_execution_history_empty_filter_cancel_and_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    ui = presenter(fake, monkeypatch)
    store = SimpleNamespace(nodes=lambda execution_id: {"node": {"status": "SUCCESS"}})
    cancelled: list[str] = []
    submitted: list[Any] = []
    enqueued: list[str] = []

    def submit(*args: Any, **kwargs: Any) -> Any:
        submitted.append((args, kwargs))
        return SimpleNamespace(id="replay-1")

    ui.runtime = SimpleNamespace(
        engine=SimpleNamespace(
            store=store,
            cancel=lambda execution_id, user: cancelled.append(execution_id),
            submit=submit,
        ),
        worker=SimpleNamespace(enqueue=lambda execution_id: enqueued.append(execution_id)),
    )

    ui._visible_executions = lambda limit=1000: []  # type: ignore[method-assign]
    ui._executions()
    assert fake.frames[-1] == []

    pending = execution(Status.PENDING)
    ui._visible_executions = lambda limit=1000: [pending]  # type: ignore[method-assign]
    fake.clicks = {"Cancel"}
    ui._executions()
    assert cancelled == [pending.id]
    assert fake.rerun_called is True

    fake.rerun_called = False
    fake.clicks = {"Run again"}
    succeeded = execution(Status.SUCCESS)
    ui._visible_executions = lambda limit=1000: [succeeded]  # type: ignore[method-assign]
    ui._executions()
    assert submitted
    assert enqueued == ["replay-1"]
    assert fake.session_state["flowops:last_execution"] == "replay-1"
    assert fake.rerun_called is True

    fake.clicks = set()
    fake.select_values["Status"] = Status.FAILED.value
    ui._visible_executions = lambda limit=1000: [succeeded]  # type: ignore[method-assign]
    ui._executions()
    assert fake.frames[-1] == []


def test_approvals_empty_permission_filter_and_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    ui = presenter(fake, monkeypatch)
    item = {
        "execution_id": "execution-1",
        "node_id": "approval",
        "digest": "digest-1",
        "body": {"environment": "dev", "preview": {"change": True}},
    }
    target = execution(Status.WAITING_APPROVAL)
    decisions: list[tuple[Any, ...]] = []
    store = SimpleNamespace(
        pending_approvals=lambda: [item],
        get=lambda execution_id: target,
    )
    ui.runtime = SimpleNamespace(
        engine=SimpleNamespace(
            store=store,
            approve=lambda *args, **kwargs: decisions.append((args, kwargs)),
        ),
        worker=SimpleNamespace(enqueue=lambda execution_id: None),
    )
    ui._granted = lambda permission, book=None: False  # type: ignore[method-assign]
    ui._approvals()
    assert fake.infos == ["No pending approvals."]

    fake.infos.clear()
    fake.clicks = {"Reject"}
    fake.text_values["Decision reason"] = "unsafe change"
    ui._granted = lambda permission, book=None: True  # type: ignore[method-assign]
    ui._approvals()
    assert len(decisions) == 1
    args, kwargs = decisions[0]
    assert args[:3] == ("execution-1", "approval", "digest-1")
    assert kwargs == {"approved": False, "reason": "unsafe change"}
    assert fake.rerun_called is True


def test_audit_filters_visibility_and_event_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    ui = presenter(fake, monkeypatch)
    book = Runbook(name="Visible")
    visible_execution = execution(Status.SUCCESS, execution_id="visible-execution")
    events = [
        {
            "id": "e1",
            "created_at": "now",
            "actor": "operator",
            "event": "EXECUTION_COMPLETED",
            "execution_id": visible_execution.id,
            "body": {
                "environment": "dev",
                "account": "1",
                "region": "us-east-1",
                "result": "SUCCESS",
            },
        },
        {
            "id": "e2",
            "created_at": "now",
            "actor": "operator",
            "event": "RUNBOOK_CHANGED",
            "execution_id": None,
            "body": {"runbook_id": book.id, "reason": "edit"},
        },
        {
            "id": "hidden",
            "created_at": "now",
            "actor": "other",
            "event": "SECRET_EVENT",
            "execution_id": "hidden-execution",
            "body": {},
        },
    ]
    ui.repository = SimpleNamespace(events=lambda limit=1000: events)
    ui._visible_executions = lambda limit=1000: [visible_execution]  # type: ignore[method-assign]
    ui._visible_runbooks = lambda query="": [book]  # type: ignore[method-assign]
    fake.text_values["Event filter"] = "completed"
    ui._audit()
    assert len(fake.frames[-1]) == 1
    assert fake.frames[-1][0]["what"] == "EXECUTION_COMPLETED"
    assert fake.json_values[-1]["id"] == "e1"


def test_resource_explorer_denies_without_permission_and_persists_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit()
    ui = presenter(fake, monkeypatch)
    ui.runtime = SimpleNamespace(registry=SimpleNamespace())
    ui._granted = lambda permission, book=None: False  # type: ignore[method-assign]
    ui._resources()
    assert fake.warnings == ["Your identity does not have aws.read."]

    fake.warnings.clear()
    fake.clicks = {"Discover resources"}
    ui._granted = lambda permission, book=None: True  # type: ignore[method-assign]
    monkeypatch.setattr(
        "flowops.streamlit.ui.explore",
        lambda registry, user, aws, service: {"resources": [service]},
    )
    ui._resources()
    assert fake.session_state["flowops:resource-result"]
    assert fake.json_values[-1] == {"resources": ["dynamodb"]}
    assert fake.captions[-1].startswith("Resource discovery is read-only")
