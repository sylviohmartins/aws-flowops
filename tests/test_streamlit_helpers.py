from __future__ import annotations

import math

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Node, Parameter, Runbook
from flowops.streamlit.canvas import apply_canvas
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.workspace import _compatible, _duration


def canvas_book() -> Runbook:
    return Runbook(
        name="Canvas coverage",
        nodes=[
            Node(id="start", action="core.start", label="<Start>"),
            Node(id="work", action="core.validation", config={"condition": True}),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="work"),
            Edge(source="work", target="end"),
        ],
    )


def test_apply_canvas_readonly_and_valid_layout_edge_selection() -> None:
    book = canvas_book()
    readonly, selected = apply_canvas(
        book,
        {"nodes": [], "edges": [], "selected_id": "work"},
        readonly=True,
    )
    assert readonly == book
    assert readonly is not book
    assert selected is None

    result, selected = apply_canvas(
        book,
        {
            "nodes": [
                {"id": "start", "position": {"x": 10, "y": 20}},
                {"id": "work", "position": {"x": -5.5, "y": 40}},
            ],
            "edges": [{"source": "start", "target": "work", "label": "accepted"}],
            "selected_id": "work",
        },
    )
    assert [node.id for node in result.nodes] == ["start", "work"]
    assert result.nodes[0].position == (10.0, 20.0)
    assert result.nodes[1].position == (-5.5, 40.0)
    assert result.edges == [Edge(source="start", target="work", branch="accepted")]
    assert selected == "work"

    result, selected = apply_canvas(
        book,
        {
            "nodes": [
                {"id": "start"},
                {"id": "work"},
            ],
            "edges": [{"source": "start", "target": "work"}],
            "selected_id": "removed",
        },
    )
    assert result.edges[0].branch == "default"
    assert selected is None


def test_apply_canvas_rejects_size_unknown_duplicates_positions_and_removed_edges() -> None:
    book = canvas_book()
    with pytest.raises(WorkflowValidationError, match="Canvas size limit"):
        apply_canvas(book, {"nodes": [{}] * 201, "edges": []})
    with pytest.raises(WorkflowValidationError, match="Canvas size limit"):
        apply_canvas(book, {"nodes": [], "edges": [{}] * 1001})

    for nodes in (
        [{"id": "unknown"}],
        [{"id": "start"}, {"id": "start"}],
    ):
        with pytest.raises(WorkflowValidationError, match="Add or duplicate"):
            apply_canvas(book, {"nodes": nodes, "edges": []})

    for value in (math.inf, math.nan, 100001, -100001):
        with pytest.raises(WorkflowValidationError, match="Invalid canvas position"):
            apply_canvas(
                book,
                {
                    "nodes": [{"id": "start", "position": {"x": value, "y": 0}}],
                    "edges": [],
                },
            )

    with pytest.raises(WorkflowValidationError, match="removed node"):
        apply_canvas(
            book,
            {
                "nodes": [{"id": "start"}],
                "edges": [{"source": "start", "target": "end"}],
            },
        )


def test_ui_json_object_and_parameter_coercion_contracts() -> None:
    assert FlowOpsUI._json_object("", label="Config") == {}
    assert FlowOpsUI._json_object('{"enabled":true}', label="Config") == {"enabled": True}
    with pytest.raises(WorkflowValidationError, match="valid JSON"):
        FlowOpsUI._json_object("{", label="Config")
    with pytest.raises(WorkflowValidationError, match="JSON object"):
        FlowOpsUI._json_object("[]", label="Config")

    values = {
        "optional": (Parameter(type="string", required=False), ""),
        "required": (Parameter(type="string"), "value"),
        "array": (Parameter(type="array"), '[1,"two"]'),
        "object": (Parameter(type="object"), '{"key":3}'),
        "integer": (Parameter(type="integer"), 7),
        "number": (Parameter(type="number"), 2.5),
        "boolean": (Parameter(type="boolean"), True),
    }
    assert FlowOpsUI._coerce_parameters(values) == {
        "optional": None,
        "required": "value",
        "array": [1, "two"],
        "object": {"key": 3},
        "integer": 7,
        "number": 2.5,
        "boolean": True,
    }
    with pytest.raises(WorkflowValidationError, match="Parameter array must be valid JSON"):
        FlowOpsUI._coerce_parameters({"array": (Parameter(type="array"), "[")})


def test_workspace_type_compatibility_and_duration_helpers() -> None:
    assert _compatible("string", "string") is True
    assert _compatible("any", "object") is True
    assert _compatible("array", "any") is True
    assert _compatible("integer", "number") is True
    assert _compatible("number", "integer") is False

    assert _duration(None, "2026-09-06T01:00:00+00:00") is None
    assert _duration("2026-09-06T01:00:00+00:00", None) is None
    assert _duration("invalid", "also-invalid") is None
    assert (
        _duration("2026-09-06T01:00:00+00:00", "2026-09-06T01:00:03.500000+00:00")
        == 3.5
    )
    assert _duration("2026-09-06T01:00:03+00:00", "2026-09-06T01:00:00+00:00") == 0.0
