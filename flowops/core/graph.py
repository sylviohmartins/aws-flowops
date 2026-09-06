"""Deterministic DAG validation and bounded typed parameter binding."""

from collections import defaultdict
from graphlib import CycleError, TopologicalSorter
from typing import Any

from flowops.core.actions import ActionRegistry
from flowops.core.expressions import path_parts, references
from flowops.core.mapping import validate_mapping_types
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook

LOGIC_REQUIRED = {
    "core.start": [],
    "core.end": [],
    "core.condition": ["left"],
    "core.switch": ["value", "cases"],
    "core.filter": ["items", "path", "value"],
    "core.map": ["items", "template"],
    "core.for_each": ["items", "template"],
    "core.batch": ["items", "size"],
    "core.parallel": [],
    "core.merge": [],
    "core.wait": ["seconds"],
    "core.retry": ["action", "config"],
    "core.compensation": ["action", "config"],
    "core.stop": [],
    "core.validation": ["left"],
    "core.approval": [],
}


def validate_graph(book: Runbook, registry: ActionRegistry | None = None) -> list[str]:
    if not book.nodes or len(book.nodes) > 200 or len(book.edges) > 1000:
        raise WorkflowValidationError("A workflow needs 1–200 nodes and at most 1000 edges.")
    nodes = {n.id: n for n in book.nodes}
    if len(nodes) != len(book.nodes):
        raise WorkflowValidationError("Node IDs must be unique.")
    iteration_prefixes = [node.id[:48] for node in book.nodes if node.action == "core.for_each"]
    if len(iteration_prefixes) != len(set(iteration_prefixes)) or any(
        node_id.startswith(f"{prefix}__") and node_id[len(prefix) + 2:].isdigit()
        for prefix in iteration_prefixes for node_id in nodes
    ):
        raise WorkflowValidationError("Iteration checkpoint IDs must not overlap graph nodes or other iterations.")
    starts = [n.id for n in book.nodes if n.action == "core.start"]
    ends = [n.id for n in book.nodes if n.action in {"core.end", "core.stop"}]
    if len(starts) != 1 or not ends:
        raise WorkflowValidationError("Use exactly one Start and at least one End or Stop.")
    incoming: dict[str, set[str]] = {n: set() for n in nodes}
    outgoing: dict[str, set[str]] = defaultdict(set)
    seen: set[tuple[str, str, str]] = set()
    for edge in book.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise WorkflowValidationError("An edge refers to an unknown node.")
        edge_key = (edge.source, edge.target, edge.branch)
        if edge_key in seen:
            raise WorkflowValidationError("Duplicate edge.")
        seen.add(edge_key)
        incoming[edge.target].add(edge.source)
        outgoing[edge.source].add(edge.target)
        source = nodes[edge.source]
        allowed = {"default"}
        if source.action == "core.condition":
            allowed = {"true", "false"}
        elif source.action == "core.switch":
            allowed |= set(source.config.get("cases", {}))
        if source.failure_policy == "FAIL_BRANCH":
            allowed.add("failure")
        if edge.branch not in allowed:
            raise WorkflowValidationError(f"Invalid branch {edge.branch} on {source.id}.")
    try:
        order = list(TopologicalSorter(incoming).static_order())
    except CycleError as exc:
        raise WorkflowValidationError("Cycles are forbidden; use bounded For Each.") from exc
    if incoming[starts[0]] or any(outgoing[end] for end in ends):
        raise WorkflowValidationError("Start has no input; End/Stop has no output.")
    for node in book.nodes:
        if node.failure_policy == "FAIL_BRANCH" and not any(
            edge.source == node.id and edge.branch == "failure" for edge in book.edges
        ):
            raise WorkflowValidationError(f"{node.id}: FAIL_BRANCH requires a failure edge.")
    ancestors: dict[str, set[str]] = {}
    for node_id in order:
        ancestors[node_id] = set(incoming[node_id])
        for parent in incoming[node_id]:
            ancestors[node_id].update(ancestors[parent])
        if node_id != starts[0] and starts[0] not in ancestors[node_id]:
            raise WorkflowValidationError(f"Disconnected node: {node_id}.")
        if not outgoing[node_id] and node_id not in ends:
            raise WorkflowValidationError(f"Connect {node_id} to an End or Stop.")
        node = nodes[node_id]
        if node.action in LOGIC_REQUIRED:
            required = LOGIC_REQUIRED[node.action]
        elif registry is not None:
            required = registry.get(node.action).metadata.input_schema.get("required", [])
        else:
            required = []
        for key in required:
            if key not in node.config:
                raise WorkflowValidationError(f"{node_id}: required input {key} is missing.")
        if registry is not None and node.action in {"core.retry", "core.compensation"}:
            nested_action = node.config.get("action")
            if not isinstance(nested_action, str):
                raise WorkflowValidationError(f"{node_id}: nested action must be a string.")
            registry.get(nested_action)
        for ref in references(node.config):
            parts = path_parts(ref)
            if parts[0] == "nodes":
                if len(parts) < 3 or parts[1] not in ancestors[node_id] or parts[2] != "output":
                    raise WorkflowValidationError(
                        f"{node_id}: output reference must target an ancestor."
                    )
            elif parts[0] == "params":
                if len(parts) < 2 or parts[1] not in book.parameters:
                    raise WorkflowValidationError(f"{node_id}: parameter does not exist.")
            elif parts[0] == "item":
                if node.action not in {"core.map", "core.for_each"}:
                    raise WorkflowValidationError(
                        "item references are limited to explicit iterations."
                    )
            elif parts[0] not in {"input", "context"}:
                raise WorkflowValidationError("Unknown expression root.")
        if registry is not None:
            validate_mapping_types(book, node, ancestors[node_id], registry)
    return order


def bind_parameters(book: Runbook, supplied: dict[str, Any]) -> dict[str, Any]:
    if supplied.keys() - book.parameters.keys():
        raise WorkflowValidationError("Unknown runbook parameter.")
    types: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    bound: dict[str, Any] = {}
    for key, spec in book.parameters.items():
        value = supplied.get(key, spec.default)
        if value is None:
            if spec.required:
                raise WorkflowValidationError(f"Required parameter: {key}.")
            bound[key] = None
            continue
        if type(value) not in types[spec.type]:
            raise WorkflowValidationError(f"Parameter {key} must be {spec.type}.")
        bound[key] = value
    return bound
