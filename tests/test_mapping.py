from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.graph import validate_graph
from flowops.core.mapping import apply_mapping, defaults_from_schema, flatten_schema, source_fields
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Node, Runbook


class FakeAction:
    def __init__(self, metadata: Metadata):
        self.metadata = metadata

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config


def registry() -> ActionRegistry:
    actions = ActionRegistry()
    actions.register(
        FakeAction(
            Metadata(
                "fake.source",
                "fake",
                "fake",
                "source",
                "Typed source",
                output_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Record identifier"},
                        "count": {"type": "integer"},
                    },
                },
            )
        )
    )
    actions.register(
        FakeAction(
            Metadata(
                "fake.target",
                "fake",
                "fake",
                "target",
                "Typed target",
                input_schema={
                    "type": "object",
                    "required": ["Name"],
                    "properties": {
                        "Name": {"type": "string", "description": "Target name"},
                        "Limit": {"type": "integer", "default": 10},
                    },
                },
            )
        )
    )
    return actions


def book() -> Runbook:
    return Runbook(
        name="mapping",
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="source", action="fake.source"),
            Node(
                id="target", action="fake.target", config={"Name": "{{ nodes.source.output.id }}"}
            ),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="source"),
            Edge(source="source", target="target"),
            Edge(source="target", target="end"),
        ],
    )


def test_schema_browser_defaults_and_source_autocomplete() -> None:
    schema = registry().get("fake.target").metadata.input_schema
    fields = {field.path: field for field in flatten_schema(schema)}
    assert fields["Name"].required is True
    assert fields["Name"].description == "Target name"
    assert defaults_from_schema(schema) == {"Limit": 10}
    sources = {field.path: field.type for field in source_fields(book(), "target", registry())}
    assert sources["nodes.source.output.id"] == "string"
    assert sources["nodes.source.output.count"] == "integer"


def test_mapping_preview_and_graph_type_validation() -> None:
    runbook = book()
    target = next(node for node in runbook.nodes if node.id == "target")
    target.config = apply_mapping({}, "Name", "nodes.source.output.id")
    assert target.config == {"Name": "{{ nodes.source.output.id }}"}
    validate_graph(runbook, registry())

    target.config = apply_mapping({}, "Name", "nodes.source.output.count")
    with pytest.raises(WorkflowValidationError, match="mapping integer -> string"):
        validate_graph(runbook, registry())
