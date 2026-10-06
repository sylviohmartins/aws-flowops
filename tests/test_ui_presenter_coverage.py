from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Identity, Parameter, Runbook, Status
from flowops.streamlit.ui import FlowOpsUI


class Column:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, Any]] = []

    def metric(self, label: str, value: Any) -> None:
        self.metrics.append((label, value))


class Sidebar:
    def container(self, *, key: str):
        assert key == "flowops-navigation"
        return self

    def __init__(self) -> None:
        self.page = "Dashboard"
        self.captions: list[str] = []

    def selectbox(self, label: str, options: list[str], *, key: str, **kwargs: Any) -> str:
        assert label == "Área de trabalho"
        return options[0]

    def radio(self, label: str, options: list[str], *, key: str, **kwargs: Any) -> str:
        assert self.page in options
        return self.page

    def caption(self, value: str) -> None:
        self.captions.append(value)


class FakeStreamlit:
    def expander(self, *args, **kwargs):
        from contextlib import nullcontext

        return nullcontext()

    def code(self, value, **kwargs):
        self.captions.append(value)

    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.sidebar = Sidebar()
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.captions: list[str] = []
        self.subheaders: list[str] = []
        self.frames: list[Any] = []
        self.columns_result = [Column() for _ in range(5)]
        self.selected: str | None = None

    def info(self, value: str) -> None:
        self.infos.append(value)

    def error(self, value: str) -> None:
        self.errors.append(value)

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def subheader(self, value: str) -> None:
        self.subheaders.append(value)

    def header(self, value: str) -> None:
        self.subheaders.append(value)

    def columns(self, count: int) -> list[Column]:
        assert count == 5
        return self.columns_result

    def dataframe(self, rows: Any, **kwargs: Any) -> None:
        self.frames.append(rows)

    def selectbox(
        self,
        label: str,
        options: list[str],
        *,
        index: int = 0,
        format_func: Any = None,
        key: str | None = None,
        on_change: Any = None,
    ) -> str:
        value = self.selected if self.selected in options else options[index]
        if format_func is not None:
            assert format_func(value)
        previous = self.session_state.get(key) if key is not None else None
        if key is not None:
            self.session_state[key] = value
        if on_change is not None and value != previous:
            on_change()
        return value

    def checkbox(self, label: str, *, value: bool = False, **kwargs: Any) -> bool:
        return value

    def number_input(self, label: str, *, value: Any, **kwargs: Any) -> Any:
        return value

    def text_area(self, label: str, *, value: str, **kwargs: Any) -> str:
        return value

    def text_input(self, label: str, *, value: str = "", **kwargs: Any) -> str:
        return value


def ui() -> FlowOpsUI:
    value = FlowOpsUI.__new__(FlowOpsUI)
    value.user = Identity(id="operator", display_name="Operator", roles=["ADMIN"])
    return value


def test_json_object_and_parameter_coercion_contract() -> None:
    assert FlowOpsUI._json_object("", label="Config") == {}
    assert FlowOpsUI._json_object('{"ok":1}', label="Config") == {"ok": 1}
    with pytest.raises(WorkflowValidationError, match="JSON válido"):
        FlowOpsUI._json_object("{", label="Config")
    with pytest.raises(WorkflowValidationError, match="objeto JSON"):
        FlowOpsUI._json_object("[]", label="Config")

    values = {
        "items": (Parameter(type="array"), "[1, 2]"),
        "config": (Parameter(type="object"), '{"a": true}'),
        "optional": (Parameter(type="string", required=False), ""),
        "required": (Parameter(type="string", required=True), "x"),
    }
    assert FlowOpsUI._coerce_parameters(values) == {
        "items": [1, 2],
        "config": {"a": True},
        "optional": None,
        "required": "x",
    }
    with pytest.raises(WorkflowValidationError, match="Parâmetro items"):
        FlowOpsUI._coerce_parameters({"items": (Parameter(type="array"), "[")})


def test_parameter_inputs_render_every_supported_type(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    book = Runbook(
        name="Parâmetros",
        parameters={
            "flag": Parameter(type="boolean", default=True, description="flag help"),
            "count": Parameter(type="integer", default=2),
            "ratio": Parameter(type="number", default=1.5),
            "items": Parameter(type="array", default=["a"]),
            "config": Parameter(type="object", default={"a": 1}),
            "name": Parameter(type="string", default="hello"),
        },
    )
    values = ui()._parameter_inputs(book)
    assert values["flag"][1] is True
    assert values["count"][1] == 2
    assert values["ratio"][1] == 1.5
    assert values["items"][1] == '["a"]'
    assert values["config"][1] == '{"a": 1}'
    assert values["name"][1] == "hello"
    assert fake.captions == ["flag help"]


def test_selected_and_select_runbook_recover_stale_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    first = Runbook(name="First", team="ops")
    second = Runbook(name="Second", team="ops")
    presenter = ui()
    presenter.repository = SimpleNamespace(
        list_runbooks=lambda query="": [first, second],
        versions=lambda runbook_id: [1] if runbook_id == second.id else [],
    )
    presenter._granted = lambda permission, book=None: True  # type: ignore[method-assign]

    fake.session_state["flowops:selected_runbook"] = "stale"
    assert presenter._selected_id() in {first.id, second.id}
    fake.selected = second.id
    selected = presenter._select_runbook(label="Pick")
    assert selected is second
    assert fake.session_state["flowops:selected_runbook"] == second.id

    fake.selected = None
    published = presenter._select_runbook(label="Published", published_only=True)
    assert published is second

    presenter.repository = SimpleNamespace(
        list_runbooks=lambda query="": [], versions=lambda value: []
    )
    assert presenter._select_runbook() is None
    assert fake.infos[-1] == "Nenhum procedimento disponível."


def test_dashboard_metrics_cover_empty_and_populated_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    presenter = ui()
    book = Runbook(name="Payments")
    executions = [
        SimpleNamespace(
            id="ok",
            snapshot=book,
            runbook_version=1,
            aws_context=SimpleNamespace(environment="dev"),
            status=Status.SUCCESS,
            started_at=None,
            created_at="2026-09-06",
        ),
        SimpleNamespace(
            id="fail",
            snapshot=book,
            runbook_version=1,
            aws_context=SimpleNamespace(environment="production"),
            status=Status.FAILED,
            started_at="2026-09-06",
            created_at="2026-09-06",
        ),
    ]
    presenter._visible_runbooks = lambda query="": [book]  # type: ignore[method-assign]
    presenter._visible_executions = lambda limit=1000: executions  # type: ignore[method-assign]
    presenter._dashboard()
    metrics = [item for column in fake.columns_result for item in column.metrics]
    assert ("Procedimentos", 1) in metrics
    assert ("Execuções", 2) in metrics
    assert ("Taxa de sucesso", "50,0%") in metrics
    assert len(fake.frames[-1]) == 2

    fake.columns_result = [Column() for _ in range(5)]
    presenter._visible_executions = lambda limit=1000: []  # type: ignore[method-assign]
    presenter._dashboard()
    metrics = [item for column in fake.columns_result for item in column.metrics]
    assert ("Taxa de sucesso", "—") in metrics


def test_render_routes_page_and_surfaces_domain_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    presenter = ui()
    called: list[str] = []
    presenter._dashboard = lambda: called.append("dashboard")  # type: ignore[method-assign]
    presenter.render()
    assert called == ["dashboard"]
    assert fake.sidebar.captions == ["Operator", "Perfis de acesso: Administrador"]

    def fail() -> None:
        raise WorkflowValidationError("bad page")

    presenter._dashboard = fail  # type: ignore[method-assign]
    presenter.render()
    assert fake.errors == [
        "Não foi possível concluir a operação. Consulte os detalhes técnicos para identificar a causa."
    ]
    assert "bad page" in fake.captions
