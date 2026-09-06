from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Runbook, Status
from flowops.streamlit.workspace import FlowOpsWorkspaceUI


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.inputs: dict[str, str] = {}
        self.simulation = True
        self.submitted = False
        self.captions: list[str] = []
        self.warnings: list[str] = []
        self.successes: list[str] = []

    def header(self, value: str) -> None:
        assert value == "Execute Runbook"

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def warning(self, value: str) -> None:
        self.warnings.append(value)

    def selectbox(self, label: str, options: list[int], *, key: str) -> int:
        assert label == "Version"
        return options[0]

    def form(self, key: str) -> FakeStreamlit:
        return self

    def __enter__(self) -> FakeStreamlit:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def checkbox(self, label: str, *, value: bool) -> bool:
        assert label == "FlowOps simulation"
        return self.simulation

    def text_input(self, label: str) -> str:
        return self.inputs.get(label, "")

    def form_submit_button(self, label: str, *, type: str) -> bool:
        assert label == "Submit execution"
        return self.submitted

    def success(self, value: str) -> None:
        self.successes.append(value)


class Repository:
    def __init__(self, book: Runbook) -> None:
        self.book = book

    def versions(self, runbook_id: str) -> list[int]:
        assert runbook_id == self.book.id
        return [1]

    def version(self, runbook_id: str, version: int) -> Runbook:
        assert runbook_id == self.book.id
        assert version == 1
        return self.book


class Store:
    def __init__(self) -> None:
        self.raise_missing = False

    def get(self, execution_id: str) -> Any:
        if self.raise_missing:
            from flowops.domain.errors import WorkflowValidationError

            raise WorkflowValidationError("missing")
        return SimpleNamespace(status=Status.SUCCESS)


class Engine:
    def __init__(self) -> None:
        self.store = Store()
        self.calls: list[dict[str, Any]] = []

    def submit(
        self,
        book: Runbook,
        user: Identity,
        aws: AWSContext,
        parameters: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "book": book,
                "user": user,
                "aws": aws,
                "parameters": parameters,
                **kwargs,
            }
        )
        return SimpleNamespace(id="execution-1")


class Worker:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, execution_id: str) -> None:
        self.enqueued.append(execution_id)


def ui_for(
    book: Runbook, *, environment: str = "production"
) -> tuple[FlowOpsWorkspaceUI, Engine, Worker]:
    ui = FlowOpsWorkspaceUI.__new__(FlowOpsWorkspaceUI)
    ui.user = Identity(id="operator", roles=["ADMIN"])
    ui.aws = AWSContext(
        mode="demo",
        environment=environment,
        account_id="123456789012",
        region="us-east-1",
    )
    ui.repository = Repository(book)
    engine = Engine()
    worker = Worker()
    ui.runtime = SimpleNamespace(engine=engine, worker=worker)
    ui.correlation_context = {"ticket": "CHG-42"}
    ui._select_runbook = lambda **kwargs: book  # type: ignore[method-assign]
    ui._parameter_inputs = lambda selected: {"raw": "value"}  # type: ignore[method-assign]
    ui._coerce_parameters = lambda values: {"parsed": values["raw"]}  # type: ignore[method-assign]
    return ui, engine, worker


def test_execute_returns_when_no_published_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    ui = FlowOpsWorkspaceUI.__new__(FlowOpsWorkspaceUI)
    ui._select_runbook = lambda **kwargs: None  # type: ignore[method-assign]
    ui._execute()
    assert fake.captions == []


def test_execute_requires_exact_live_production_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit()
    fake.simulation = False
    fake.submitted = True
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    book = Runbook(name="Published", version=1)
    ui, engine, worker = ui_for(book)

    with pytest.raises(WorkflowValidationError, match="exact target account"):
        ui._execute()

    assert engine.calls == []
    assert worker.enqueued == []
    assert fake.warnings and "PRODUCTION target" in fake.warnings[0]
    assert any("ticket=CHG-42" in caption for caption in fake.captions)


def test_execute_submits_enqueues_and_reads_last_status(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    fake.simulation = False
    fake.submitted = True
    fake.inputs = {
        "Reason / change reference": "approved change",
        "Type PRODUCTION for a live production run": "PRODUCTION",
        "Type the 12-digit target AWS account": "123456789012",
    }
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    book = Runbook(name="Published", version=1)
    ui, engine, worker = ui_for(book)

    ui._execute()

    assert worker.enqueued == ["execution-1"]
    assert fake.session_state["flowops:last_execution"] == "execution-1"
    assert fake.successes == ["Execution execution-1 submitted asynchronously."]
    assert engine.calls[0]["parameters"] == {"parsed": "value"}
    assert engine.calls[0]["dry_run"] is False
    assert engine.calls[0]["reason"] == "approved change"
    assert engine.calls[0]["correlation_context"] == {"ticket": "CHG-42"}
    assert any("Latest submitted status: SUCCESS" in caption for caption in fake.captions)


def test_execute_simulation_skips_production_confirmation_and_ignores_stale_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit()
    fake.simulation = True
    fake.submitted = True
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    book = Runbook(name="Published", version=1)
    ui, engine, worker = ui_for(book)
    engine.store.raise_missing = True

    ui._execute()

    assert len(engine.calls) == 1
    assert engine.calls[0]["dry_run"] is True
    assert worker.enqueued == ["execution-1"]
    assert not any("Latest submitted status" in caption for caption in fake.captions)
