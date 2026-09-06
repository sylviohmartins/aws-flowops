"""Schema-driven data mapping helpers shared by validation and Streamlit.

The mapper never evaluates Python. Sources are restricted to the same expression paths accepted
by the execution engine, and type checks use Action metadata plus Runbook parameter schemas.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from flowops.core.actions import ActionRegistry
from flowops.core.expressions import EXPRESSION, path_parts
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Node, Runbook

TARGET_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")


@dataclass(frozen=True)
class SchemaField:
    path: str
    type: str
    required: bool = False
    description: str = ""
    default: Any = None
    enum: tuple[Any, ...] = ()


def flatten_schema(
    schema: dict[str, Any], prefix: str = "", *, required: bool = False, depth: int = 0
) -> list[SchemaField]:
    """Flatten bounded JSON-schema-like botocore metadata for browsing in the editor."""
    if depth > 8:
        return []
    kind = str(schema.get("type", "any"))
    properties = schema.get("properties")
    if kind == "object" and isinstance(properties, dict) and properties:
        required_names = set(schema.get("required", []))
        rows: list[SchemaField] = []
        for name, child in properties.items():
            if not isinstance(child, dict):
                continue
            path = f"{prefix}.{name}" if prefix else str(name)
            rows.extend(
                flatten_schema(
                    child,
                    path,
                    required=name in required_names,
                    depth=depth + 1,
                )
            )
        return rows
    return [
        SchemaField(
            prefix or "$",
            kind,
            required,
            str(schema.get("description", "")),
            schema.get("default"),
            tuple(schema.get("enum", []) or []),
        )
    ]


def defaults_from_schema(schema: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Build only explicit defaults; never invent required operational values."""
    if depth > 8 or schema.get("type") != "object":
        return {}
    result: dict[str, Any] = {}
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return result
    for name, child in properties.items():
        if not isinstance(child, dict):
            continue
        if "default" in child:
            result[str(name)] = copy.deepcopy(child["default"])
        elif child.get("type") == "object":
            nested = defaults_from_schema(child, depth + 1)
            if nested:
                result[str(name)] = nested
    return result


def _schema_at(schema: dict[str, Any], parts: list[str]) -> dict[str, Any] | None:
    current: dict[str, Any] = schema
    for part in parts:
        if current.get("type") == "array":
            item = current.get("items")
            if not isinstance(item, dict):
                return None
            current = item
        properties = current.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return None
        child = properties[part]
        if not isinstance(child, dict):
            return None
        current = child
    return current


def _ancestors(book: Runbook, node_id: str) -> set[str]:
    parents = {edge.source for edge in book.edges if edge.target == node_id}
    ancestors = set(parents)
    frontier = set(parents)
    while frontier:
        parent = frontier.pop()
        grandparents = {edge.source for edge in book.edges if edge.target == parent}
        unseen = grandparents - ancestors
        ancestors.update(unseen)
        frontier.update(unseen)
    return ancestors


def source_fields(book: Runbook, node_id: str, registry: ActionRegistry) -> list[SchemaField]:
    """Return safe autocomplete sources available to a node from parameters/context/ancestors."""
    rows = [
        SchemaField(f"params.{name}", spec.type, True, spec.description, spec.default)
        for name, spec in sorted(book.parameters.items())
    ]
    rows.extend(
        [
            SchemaField("context.execution_id", "string"),
            SchemaField("context.environment", "string"),
            SchemaField("context.account", "string"),
            SchemaField("context.region", "string"),
        ]
    )
    nodes = {node.id: node for node in book.nodes}
    for ancestor_id in sorted(_ancestors(book, node_id)):
        ancestor = nodes[ancestor_id]
        if ancestor.action.startswith("core."):
            rows.append(SchemaField(f"nodes.{ancestor_id}.output", "any"))
            continue
        metadata = registry.get(ancestor.action).metadata
        fields = flatten_schema(metadata.output_schema)
        if fields == [SchemaField("$", "object")]:
            rows.append(SchemaField(f"nodes.{ancestor_id}.output", "object"))
            continue
        for field in fields:
            suffix = "" if field.path == "$" else f".{field.path}"
            rows.append(
                SchemaField(
                    f"nodes.{ancestor_id}.output{suffix}",
                    field.type,
                    field.required,
                    field.description,
                    field.default,
                    field.enum,
                )
            )
    return rows


def apply_mapping(config: dict[str, Any], target_path: str, source_path: str) -> dict[str, Any]:
    """Return a copy with a full-expression mapping assigned to a nested object property."""
    if not TARGET_PATH.fullmatch(target_path):
        raise WorkflowValidationError("Mapper target supports nested object fields separated by dots.")
    path_parts(source_path)
    result = copy.deepcopy(config)
    current = result
    target = target_path.split(".")
    for part in target[:-1]:
        existing = current.get(part)
        if existing is None:
            current[part] = {}
        elif not isinstance(existing, dict):
            raise WorkflowValidationError(f"Mapper target {part} is not an object.")
        current = current[part]
    current[target[-1]] = f"{{{{ {source_path} }}}}"
    return result


def _source_type(
    book: Runbook, source: str, registry: ActionRegistry, ancestors: set[str]
) -> str | None:
    parts = path_parts(source)
    root = parts[0]
    if root == "params" and len(parts) >= 2 and isinstance(parts[1], str):
        spec = book.parameters.get(parts[1])
        return spec.type if spec else None
    if root == "context":
        return "string"
    if root != "nodes" or len(parts) < 3 or not isinstance(parts[1], str):
        return None
    node_id = parts[1]
    if node_id not in ancestors or parts[2] != "output":
        return None
    source_node = next((node for node in book.nodes if node.id == node_id), None)
    if source_node is None or source_node.action.startswith("core."):
        return None
    schema = registry.get(source_node.action).metadata.output_schema
    remaining = [part for part in parts[3:] if isinstance(part, str)]
    target = _schema_at(schema, remaining) if remaining else schema
    if target is None:
        raise WorkflowValidationError(f"Mapped source {source} is absent from the output schema.")
    return str(target.get("type", "any"))


def _compatible(source: str | None, target: str | None) -> bool:
    if not source or not target or "any" in {source, target}:
        return True
    if source == target:
        return True
    return source == "integer" and target == "number"


def validate_mapping_types(
    book: Runbook, node: Node, ancestors: set[str], registry: ActionRegistry
) -> None:
    """Fail closed for schema-known full-expression type mismatches."""
    if node.action.startswith("core."):
        return
    input_schema = registry.get(node.action).metadata.input_schema

    def walk(value: Any, schema: dict[str, Any] | None, path: str = "") -> None:
        if isinstance(value, str):
            full = EXPRESSION.fullmatch(value.strip())
            if full and schema is not None:
                source = full.group(1).strip()
                source_type = _source_type(book, source, registry, ancestors)
                target_type = str(schema.get("type", "any"))
                if not _compatible(source_type, target_type):
                    raise WorkflowValidationError(
                        f"{node.id}: mapping {source_type} -> {target_type} is invalid at {path}."
                    )
            return
        if isinstance(value, dict):
            properties = schema.get("properties", {}) if schema else {}
            for key, child in value.items():
                child_schema = properties.get(key) if isinstance(properties, dict) else None
                walk(child, child_schema if isinstance(child_schema, dict) else None, f"{path}.{key}".strip("."))
            return
        if isinstance(value, list):
            item_schema = schema.get("items") if schema else None
            for index, child in enumerate(value):
                walk(
                    child,
                    item_schema if isinstance(item_schema, dict) else None,
                    f"{path}[{index}]",
                )

    walk(node.config, input_schema)
