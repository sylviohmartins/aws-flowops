"""A labeled, fictitious sample for pure collection logic. Never execute a provider."""

from typing import Any

from flowops.core.expressions import resolve
from flowops.core.logic import logic
from flowops.core.mapping import _ancestors
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Node, Runbook
from flowops.streamlit.flow_journey import ordered_nodes

COLLECTIONS = {"core.map", "core.filter", "core.for_each", "core.batch"}


def collection_preview(book: Runbook, node: Node, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return _preview(book, node, config)
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowValidationError(
            "A configuração não corresponde ao exemplo fictício. Confira campos obrigatórios, tipos e origens; nada foi executado ou aplicado."
        ) from exc


def _preview(book: Runbook, node: Node, config: dict[str, Any]) -> dict[str, Any]:
    if node.action not in COLLECTIONS:
        raise WorkflowValidationError(
            "A prévia fictícia está disponível somente para transformar listas."
        )
    example = [
        {"paymentId": {"S": "12345"}, "status": {"S": "PROCESSING"}, "amount": {"N": "149.90"}}
    ]
    examples = {
        "string": "exemplo",
        "integer": 1,
        "number": 1.0,
        "boolean": False,
        "object": {},
        "array": [],
    }
    scope: dict[str, Any] = {
        "params": {name: examples[spec.type] for name, spec in book.parameters.items()},
        "context": {
            "environment": "dev",
            "account": "000000000000",
            "region": "sa-east-1",
            "execution_id": "exemplo-ficticio",
        },
        "nodes": {},
        "input": {},
    }
    nodes = {item.id: item for item in book.nodes}
    needed = _ancestors(book, node.id) | {node.id}
    for node_id in ordered_nodes(book):
        if node_id not in needed:
            continue
        current = nodes[node_id]
        raw = config if node_id == node.id else current.config
        if current.action == "dynamodb.query":
            output = {"Items": example, "Count": 1, "ScannedCount": 1}
        elif current.action == "dynamodb.get_item":
            output = {"Item": example[0]}
        elif current.action in COLLECTIONS:
            prepared = resolve(
                {name: value for name, value in raw.items() if name != "template"}, scope
            )
            if "template" in raw:
                prepared["template"] = raw["template"]
            output, _ = logic(current.action, prepared, scope, limit=3)
        else:
            # Unknown actions have no invented outputs; lookups fail if a later node uses them.
            continue
        scope["nodes"][node_id] = {"output": output}
        if node_id == node.id:
            return dict(output)
    raise WorkflowValidationError("A etapa não faz parte deste fluxo.")
