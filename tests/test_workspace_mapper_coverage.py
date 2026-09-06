from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.core.actions import ActionRegistry, Metadata
from flowops.domain.models import Edge, Identity, Node, Parameter, Runbook
from flowops.persistence.repository import Repository
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.workspace import FlowOpsWorkspaceUI


class DummyAction:
    def __init__(self, metadata: Metadata) -> None:
        self.metadata = metadata

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: Any) -> Any:
        return {}

    def execute(self, config: dict[str, Any], context: Any) -> Any:
        return {}


class Block:
    def __enter__(self) -> Block:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class ButtonColumn:
    def __init__(self, fake: FakeStreamlit, index: int) -> None:
        self.fake = fake
        self.index = index

    def button(self, label: str, **kwargs: Any) -> bool:
        disabled = bool(kwargs.get("disabled", False))
        return not disabled and label in self.fake.clicks


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.clicks: set[str] = set()
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.errors: list[str] = []
        self.captions: list[str] = []
        self.frames: list[Any] = []
        self.json_values: list[Any] = []
        self.rerun_called = False
        self.selections: dict[str, str] = {}

    def subheader(self, value: str) -> None:
        return None

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def expander(self, label: str, **kwargs: Any) -> Block:
        return Block()

    def dataframe(self, rows: Any, **kwargs: Any) -> None:
        self.frames.append(rows)

    def info(self, value: str) -> None:
        self.infos.append(value)

    def success(self, value: str) -> None:
        self.successes.append(value)

    def error(self, value: str) -> None:
        self.errors.append(value)

    def selectbox(self, label: str, options: list[str], **kwargs: Any) -> str:
        chosen = self.selections.get(label)
        value = chosen if chosen in options else options[0]
        format_func = kwargs.get("format_func")
        if callable(format_func):
            assert format_func(value)
        return value

    def markdown(self, value: str) -> None:
        return None

    def json(self, value: Any, **kwargs: Any) -> None:
        self.json_values.append(value)

    def columns(self, count: int) -> list[ButtonColumn]:
        return [ButtonColumn(self, index) for index in range(count)]

    def rerun(self) -> None:
        self.rerun_called = True


def registry(input_schema: dict[str, Any]) -> ActionRegistry:
    value = ActionRegistry()
    value.register(
        DummyAction(
            Metadata(
                id="test.update",
                provider="test",
                service="test",
                operation="update",
                description="test action",
                input_schema=input_schema,
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
        )
    )
    return value


def build_ui(
    tmp_path: Any,
    fake: FakeStreamlit,
    monkeypatch: pytest.MonkeyPatch,
    *,
    input_schema: dict[str, Any],
    parameters: dict[str, Parameter] | None = None,
) -> tuple[FlowOpsWorkspaceUI, Runbook, int]:
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(FlowOpsUI, "_editor", lambda self: None)
    repo = Repository(tmp_path / "mapper.db")
    book = Runbook(
        name="Mapper",
        parameters=parameters or {},
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="target", action="test.update", config={}),
        ],
        edges=[Edge(source="start", target="target")],
    )
    revision = repo.save_draft(book, "operator")
    fake.session_state["flowops:selected_runbook"] = book.id
    fake.session_state[f"flowops:node:{book.id}"] = "target"
    ui = FlowOpsWorkspaceUI.__new__(FlowOpsWorkspaceUI)
    ui.user = Identity(id="operator", roles=["ADMIN"])
    ui.repository = repo
    ui.runtime = SimpleNamespace(registry=registry(input_schema))
    return ui, book, revision


def test_mapper_returns_for_missing_selection_draft_and_core_node(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(FlowOpsUI, "_editor", lambda self: None)
    ui = FlowOpsWorkspaceUI.__new__(FlowOpsWorkspaceUI)
    ui.repository = SimpleNamespace(get_draft=lambda selected: (_ for _ in ()).throw(Exception()))
    ui._editor()

    repo = Repository(tmp_path / "early.db")
    core = Runbook(name="Core", nodes=[Node(id="start", action="core.start")])
    revision = repo.save_draft(core, "operator")
    fake.session_state["flowops:selected_runbook"] = core.id
    fake.session_state[f"flowops:node:{core.id}"] = "start"
    ui.repository = repo
    ui.runtime = SimpleNamespace(registry=ActionRegistry())
    ui.user = Identity(id="operator", roles=["ADMIN"])
    ui._editor()
    assert revision == 1


def test_mapper_reports_no_targets_and_no_sources(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    ui, _, _ = build_ui(
        tmp_path,
        fake,
        monkeypatch,
        input_schema={"type": "object"},
    )
    ui._editor()
    assert fake.infos[-1].startswith("This action does not expose")

    fake.infos.clear()
    ui.runtime = SimpleNamespace(
        registry=registry(
            {"type": "object", "properties": {"Count": {"type": "integer"}}}
        )
    )
    monkeypatch.setattr("flowops.streamlit.workspace.source_fields", lambda *args: [])
    ui._editor()
    assert fake.infos == ["No parameter or ancestor output is available to map yet."]


def test_mapper_applies_compatible_mapping_and_schema_defaults(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    schema = {
        "type": "object",
        "properties": {
            "Count": {"type": "number"},
            "Mode": {"type": "string", "default": "safe"},
        },
    }
    ui, book, revision = build_ui(
        tmp_path,
        fake,
        monkeypatch,
        input_schema=schema,
        parameters={"count": Parameter(type="integer", default=2)},
    )
    fake.selections = {"Target field": "Count", "Source": "params.count"}
    fake.clicks = {"Apply mapping"}
    ui._editor()
    assert fake.rerun_called is True
    cached = fake.session_state[ui._working_key(book)]
    mapped = Runbook.model_validate_json(cached["body"])
    assert mapped.nodes[1].config["Count"] == "{{ params.count }}"
    assert any("integer → number" in value for value in fake.successes)
    assert fake.json_values[-1]["Count"] == "{{ params.count }}"

    fake.rerun_called = False
    fake.clicks = {"Apply schema defaults"}
    ui._editor()
    cached = fake.session_state[ui._working_key(book)]
    defaulted = Runbook.model_validate_json(cached["body"])
    assert defaulted.nodes[1].config == {"Mode": "safe", "Count": "{{ params.count }}"}
    assert cached["revision"] == revision


def test_mapper_disables_incompatible_or_readonly_mapping(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStreamlit()
    ui, book, revision = build_ui(
        tmp_path,
        fake,
        monkeypatch,
        input_schema={"type": "object", "properties": {"Flag": {"type": "boolean"}}},
        parameters={"name": Parameter(type="string")},
    )
    fake.selections = {"Target field": "Flag", "Source": "params.name"}
    fake.clicks = {"Apply mapping"}
    ui._editor()
    assert fake.errors[-1].startswith("Type mismatch")
    assert fake.rerun_called is False

    monkeypatch.setattr(ui, "_granted", lambda permission, working=None: False)
    fake.clicks = {"Apply schema defaults"}
    ui.runtime = SimpleNamespace(
        registry=registry(
            {
                "type": "object",
                "properties": {
                    "Flag": {"type": "string", "default": "off"},
                },
            }
        )
    )
    fake.selections = {"Target field": "Flag", "Source": "params.name"}
    ui._editor()
    assert fake.rerun_called is False
    cached = fake.session_state[ui._working_key(book)]
    assert cached["revision"] == revision
