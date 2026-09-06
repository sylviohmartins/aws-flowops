from __future__ import annotations

from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.mapping import (
    SchemaField,
    _compatible,
    _schema_at,
    _source_type,
    apply_mapping,
    defaults_from_schema,
    flatten_schema,
    source_fields,
    validate_mapping_types,
)
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Node, Parameter, Runbook


class FakeAction:
    def __init__(self, metadata: Metadata) -> None:
        self.metadata = metadata

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        return config


def mapper_registry() -> ActionRegistry:
    registry = ActionRegistry()
    registry.register(
        FakeAction(
            Metadata(
                "fake.source",
                "fake",
                "fake",
                "source",
                "source",
                output_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "count": {"type": "integer"},
                        "nested": {
                            "type": "object",
                            "properties": {"ratio": {"type": "number"}},
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            },
                        },
                    },
                },
            )
        )
    )
    registry.register(
        FakeAction(
            Metadata(
                "fake.opaque",
                "fake",
                "fake",
                "opaque",
                "opaque",
                output_schema={"type": "object"},
            )
        )
    )
    registry.register(
        FakeAction(
            Metadata(
                "fake.target",
                "fake",
                "fake",
                "target",
                "target",
                input_schema={
                    "type": "object",
                    "properties": {
                        "Name": {"type": "string"},
                        "Count": {"type": "number"},
                        "Payload": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                        },
                        "Entries": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            )
        )
    )
    return registry


def mapper_book() -> Runbook:
    return Runbook(
        name="mapper coverage",
        parameters={
            "name": Parameter(type="string", description="Name"),
            "count": Parameter(type="integer", required=False, default=2),
        },
        nodes=[
            Node(id="start", action="core.start"),
            Node(id="logic", action="core.parallel"),
            Node(id="source", action="fake.source"),
            Node(id="opaque", action="fake.opaque"),
            Node(id="target", action="fake.target"),
            Node(id="end", action="core.end"),
        ],
        edges=[
            Edge(source="start", target="logic"),
            Edge(source="logic", target="source"),
            Edge(source="source", target="opaque"),
            Edge(source="opaque", target="target"),
            Edge(source="target", target="end"),
        ],
    )


def test_flatten_schema_handles_metadata_bad_children_and_depth() -> None:
    schema = {
        "type": "object",
        "required": ["Good"],
        "properties": {
            "Good": {
                "type": "string",
                "description": "documented",
                "default": "x",
                "enum": ["x", "y"],
            },
            "Bad": "not-a-schema",
        },
    }
    assert flatten_schema(schema) == [
        SchemaField("Good", "string", True, "documented", "x", ("x", "y"))
    ]
    assert flatten_schema({"type": "array"}, prefix="Items") == [
        SchemaField("Items", "array")
    ]
    assert flatten_schema({"type": "string"}, depth=9) == []


def test_defaults_from_schema_only_uses_explicit_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "A": {"type": "string", "default": "a"},
            "Nested": {
                "type": "object",
                "properties": {
                    "Enabled": {"type": "boolean", "default": True},
                    "Unset": {"type": "string"},
                },
            },
            "Broken": "bad",
        },
    }
    assert defaults_from_schema(schema) == {"A": "a", "Nested": {"Enabled": True}}
    assert defaults_from_schema({"type": "string"}) == {}
    assert defaults_from_schema({"type": "object", "properties": []}) == {}
    assert defaults_from_schema(schema, depth=9) == {}


def test_schema_at_arrays_and_malformed_shapes() -> None:
    schema = {
        "type": "object",
        "properties": {
            "Items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"Id": {"type": "string"}},
                },
            }
        },
    }
    assert _schema_at(schema, ["Items", "Id"]) == {"type": "string"}
    assert _schema_at({"type": "array", "items": "bad"}, ["Id"]) is None
    assert _schema_at({"type": "object", "properties": []}, ["Id"]) is None
    assert _schema_at(
        {"type": "object", "properties": {"Id": "bad"}}, ["Id"]
    ) is None


def test_source_fields_include_context_core_opaque_and_typed_ancestors() -> None:
    fields = {field.path: field.type for field in source_fields(mapper_book(), "target", mapper_registry())}
    assert fields["params.name"] == "string"
    assert fields["params.count"] == "integer"
    assert fields["context.execution_id"] == "string"
    assert fields["context.environment"] == "string"
    assert fields["context.account"] == "string"
    assert fields["context.region"] == "string"
    assert fields["nodes.logic.output"] == "any"
    assert fields["nodes.opaque.output"] == "object"
    assert fields["nodes.source.output.name"] == "string"
    assert fields["nodes.source.output.nested.ratio"] == "number"
    assert fields["nodes.source.output.items"] == "array"


def test_apply_mapping_nested_copy_and_errors() -> None:
    original = {"Payload": {"keep": 1}}
    mapped = apply_mapping(original, "Payload.id", "params.name")
    assert mapped == {"Payload": {"keep": 1, "id": "{{ params.name }}"}}
    assert original == {"Payload": {"keep": 1}}
    assert apply_mapping({}, "Payload.id", "params.name") == {
        "Payload": {"id": "{{ params.name }}"}
    }
    with pytest.raises(WorkflowValidationError, match="nested object fields"):
        apply_mapping({}, "Payload[0]", "params.name")
    with pytest.raises(WorkflowValidationError, match="is not an object"):
        apply_mapping({"Payload": "bad"}, "Payload.id", "params.name")
    with pytest.raises(WorkflowValidationError, match="Invalid data path"):
        apply_mapping({}, "Name", "params[-1]")


def test_source_type_and_compatibility_contracts() -> None:
    book = mapper_book()
    registry = mapper_registry()
    ancestors = {"start", "logic", "source", "opaque"}
    assert _source_type(book, "params.name", registry, ancestors) == "string"
    assert _source_type(book, "params.missing", registry, ancestors) is None
    assert _source_type(book, "context.region", registry, ancestors) == "string"
    assert _source_type(book, "input.value", registry, ancestors) is None
    assert _source_type(book, "nodes.target.output.Name", registry, ancestors) is None
    assert _source_type(book, "nodes.source.input.name", registry, ancestors) is None
    assert _source_type(book, "nodes.logic.output.value", registry, ancestors) is None
    assert _source_type(book, "nodes.source.output", registry, ancestors) == "object"
    assert _source_type(book, "nodes.source.output.nested.ratio", registry, ancestors) == "number"
    with pytest.raises(WorkflowValidationError, match="absent from the output schema"):
        _source_type(book, "nodes.source.output.missing", registry, ancestors)

    assert _compatible(None, "string")
    assert _compatible("string", None)
    assert _compatible("any", "object")
    assert _compatible("integer", "integer")
    assert _compatible("integer", "number")
    assert not _compatible("number", "integer")


def test_validate_mapping_types_covers_dict_list_unknown_and_core_paths() -> None:
    book = mapper_book()
    registry = mapper_registry()
    ancestors = {"start", "logic", "source", "opaque"}
    target = next(node for node in book.nodes if node.id == "target")

    validate_mapping_types(book, next(node for node in book.nodes if node.id == "logic"), ancestors, registry)

    target.config = {
        "Name": "{{ params.name }}",
        "Count": "{{ params.count }}",
        "Payload": {"id": "{{ nodes.source.output.name }}", "ignored": "literal"},
        "Entries": ["{{ params.name }}", "literal"],
        "Unknown": {"nested": "{{ input.value }}"},
    }
    validate_mapping_types(book, target, ancestors, registry)

    target.config = {"Name": "{{ params.count }}"}
    with pytest.raises(WorkflowValidationError, match="integer -> string"):
        validate_mapping_types(book, target, ancestors, registry)
