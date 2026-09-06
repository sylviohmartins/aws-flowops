from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from flowops.application import FlowOpsRuntime
from flowops.domain.models import Edge, Identity, Node, Runbook
from flowops.persistence.repository import Repository
from flowops.streamlit.failure_workspace import FlowOpsGovernedUI
from flowops.streamlit.workspace import FlowOpsWorkspaceUI


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.errors: list[str] = []
        self.subheaders: list[str] = []
        self.captions: list[str] = []
        self.selected: str | None = None
        self.click = False
        self.rerun_called = False

    def error(self, value: str) -> None:
        self.errors.append(value)

    def subheader(self, value: str) -> None:
        self.subheaders.append(value)

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def selectbox(
        self,
        label: str,
        options: list[str],
        *,
        index: int,
        format_func: Any,
        key: str,
    ) -> str:
        assert label == "Failure target"
        assert format_func(options[index])
        return self.selected or options[index]

    def button(self, label: str, *, disabled: bool, key: str) -> bool:
        assert label == "Apply failure route"
        return self.click and not disabled

    def rerun(self) -> None:
        self.rerun_called = True


def runtime(tmp_path: Path) -> FlowOpsRuntime:
    return FlowOpsRuntime.demo(Repository(tmp_path / "failure-workspace.db"))


def save(runtime: FlowOpsRuntime, book: Runbook) -> int:
    return runtime.repository.save_draft(book, "operator")


def test_failure_editor_returns_without_selected_or_missing_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(FlowOpsWorkspaceUI, "_editor", lambda self: None)
    ui = FlowOpsGovernedUI(Identity(id="operator", roles=["ADMIN"]), None, runtime(tmp_path))

    ui._editor()
    assert fake.errors == []

    fake.session_state["flowops:selected_runbook"] = "missing"
    ui._editor()
    assert fake.errors == []


def test_failure_editor_ignores_non_fail_branch_and_reports_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(FlowOpsWorkspaceUI, "_editor", lambda self: None)
    app = runtime(tmp_path)
    ui = FlowOpsGovernedUI(Identity(id="operator", roles=["ADMIN"]), None, app)

    ordinary = Runbook(
        name="Ordinary",
        nodes=[Node(id="start", action="core.start"), Node(id="end", action="core.end")],
        edges=[Edge(source="start", target="end")],
    )
    save(app, ordinary)
    fake.session_state["flowops:selected_runbook"] = ordinary.id
    fake.session_state[f"flowops:node:{ordinary.id}"] = "end"
    ui._editor()
    assert fake.errors == []

    no_target = Runbook(
        name="No target",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="worker", action="core.validation", failure_policy="FAIL_BRANCH"),
        ],
        edges=[Edge(source="start", target="worker")],
    )
    save(app, no_target)
    fake.session_state["flowops:selected_runbook"] = no_target.id
    fake.session_state[f"flowops:node:{no_target.id}"] = "worker"
    ui._editor()
    assert fake.errors[-1].startswith("FAIL_BRANCH needs another node")


def test_failure_editor_applies_replaces_and_respects_edit_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(FlowOpsWorkspaceUI, "_editor", lambda self: None)
    app = runtime(tmp_path)
    book = Runbook(
        name="Recovery route",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="worker", action="core.validation", failure_policy="FAIL_BRANCH"),
            Node(id="old", action="core.end", label="Old recovery"),
            Node(id="new", action="core.end", label="New recovery"),
        ],
        edges=[
            Edge(source="start", target="worker"),
            Edge(source="worker", target="old", branch="failure"),
        ],
    )
    revision = save(app, book)
    fake.session_state["flowops:selected_runbook"] = book.id
    fake.session_state[f"flowops:node:{book.id}"] = "worker"
    fake.selected = "new"
    fake.click = True

    admin = FlowOpsGovernedUI(Identity(id="operator", roles=["ADMIN"]), None, app)
    admin._editor()
    assert fake.subheaders[-1] == "Failure route"
    assert "compensation" in fake.captions[-1]
    assert fake.rerun_called is True
    working = admin._working_draft(book, revision)
    failure_edges = [
        edge for edge in working.edges if edge.source == "worker" and edge.branch == "failure"
    ]
    assert failure_edges == [Edge(source="worker", target="new", branch="failure")]

    fake.rerun_called = False
    fake.selected = "old"
    viewer = FlowOpsGovernedUI(Identity(id="viewer", roles=["VIEWER"]), None, app)
    viewer._editor()
    assert fake.rerun_called is False
