"""Versioned, optimistic bridge for an optional React editor. No operational effects."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flowops.core.mapping import apply_mapping, flatten_schema
from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Identity, Runbook
from flowops.persistence.repository import digest
from flowops.streamlit.authoring import (
    EditBuffer,
    authoring_sources,
    reference_value,
    source_label,
    value_kind,
)
from flowops.streamlit.flow_journey import branch_options, connect
from flowops.streamlit.localization import field_label, render_error


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    op: Literal[
        "value",
        "label",
        "position",
        "connect",
        "bind",
        "disconnect",
        "add",
        "remove",
        "config_json",
    ]
    node: str = Field(max_length=160)
    path: list[str | int] = Field(default_factory=list, max_length=9)
    value: Any = None
    target: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)
    branch: str = Field(default="default", max_length=160)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal[1]
    book_id: str
    revision: int
    base: str = Field(max_length=64)
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["draft", "apply", "discard", "select"]
    operations: list[Operation] = Field(default_factory=list, max_length=100)
    selected: str | None = None


def editable_fields(config: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    def walk(value: Any, path: list[str | int]) -> None:
        if len(path) > 8 or len(fields) >= 64:
            return
        if isinstance(value, dict):
            for name, child in value.items():
                walk(child, path + [name])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + [index])
        elif (
            path
            and value is not None
            and not (
                type(value) in {float, int} and (abs(value) > 2**53 - 1 or not math.isfinite(value))
            )
        ):
            fields.append(
                {
                    "path": path,
                    "label": " / ".join(field_label(str(part)) for part in path),
                    "kind": value_kind(value),
                    "value": value,
                }
            )

    walk(config, [])
    return fields


def apply_command(
    book: Runbook, revision: int, payload: dict[str, Any], user: Identity, registry: Any
) -> Runbook:
    from flowops.streamlit.value_editor import _validate_references

    if len(json.dumps(payload)) > 250_000:
        raise WorkflowValidationError("A alteração excede o limite do editor.")
    try:
        command = Command.model_validate(payload)
    except ValidationError as exc:
        raise WorkflowValidationError(
            "Mensagem inválida do editor visual. Reabra o editor."
        ) from exc
    require(user, "runbook.edit", book)
    if (
        command.kind != "apply"
        or command.book_id != book.id
        or command.revision != revision
        or command.base != digest(book.model_dump())
    ):
        raise WorkflowValidationError(
            "O rascunho mudou. Suas alterações no canvas foram preservadas; revise antes de reaplicar."
        )
    edited = book.model_copy(deep=True)
    nodes = {node.id: node for node in edited.nodes}
    changed: set[str] = set()
    for operation in command.operations:
        node = nodes.get(operation.node)
        if node is None:
            raise WorkflowValidationError("Etapa inexistente na mensagem do editor.")
        if operation.op == "config_json":
            if not isinstance(operation.value, str):
                raise WorkflowValidationError("O editor de código deve enviar texto JSON.")
            buffer = EditBuffer.create(node.config)
            buffer.raw = operation.value
            node.config = buffer.parse_code()
            changed.add(node.id)
        elif operation.op == "value":
            slot = next(
                (
                    field
                    for field in editable_fields(node.config)
                    if field["path"] == operation.path
                ),
                None,
            )
            if slot is None or type(operation.value) not in {str, int, float, bool}:
                raise WorkflowValidationError(
                    "Campo não editável diretamente nesta caixa. Use Configuração completa."
                )
            incoming = value_kind(operation.value)
            if incoming != slot["kind"] and not (
                incoming in {"string", "reference"} and slot["kind"] in {"string", "reference"}
            ):
                raise WorkflowValidationError(
                    "Tipo do campo incompatível; use Configuração completa para trocar o tipo."
                )
            if type(operation.value) in {int, float} and (
                abs(operation.value) > 2**53 - 1 or not math.isfinite(operation.value)
            ):
                raise WorkflowValidationError("Número fora da precisão do controle visual.")
            buffer = EditBuffer.create(node.config)
            buffer.put(tuple(operation.path), operation.value)
            node.config = buffer.value
            changed.add(node.id)
        elif operation.op == "label":
            if not isinstance(operation.value, str) or not 1 <= len(operation.value.strip()) <= 120:
                raise WorkflowValidationError("Informe um nome de etapa entre 1 e 120 caracteres.")
            node.label = operation.value.strip()
        elif operation.op == "add":
            from flowops.core.graph import LOGIC_REQUIRED
            from flowops.domain.models import Edge, Node, new_id
            from flowops.streamlit.node_editor import initial_config

            action = operation.value
            if not isinstance(action, str) or action in {"core.start", "core.end"}:
                raise WorkflowValidationError("Escolha uma ação da biblioteca.")
            if action not in LOGIC_REQUIRED:
                registry.get(action)
            if node.action != "core.end" or len(edited.nodes) >= 200:
                raise WorkflowValidationError(
                    "Selecione o fim de um fluxo com menos de 200 etapas."
                )
            inserted = Node(
                id=f"n_{new_id()[:12]}",
                action=action,
                label=action,
                config=initial_config(action),
                position=node.position,
            )
            node.position = (node.position[0] + 340, node.position[1])
            for edge in edited.edges:
                if edge.target == node.id:
                    edge.target = inserted.id
            edited.edges.append(Edge(source=inserted.id, target=node.id))
            edited.nodes.append(inserted)
            nodes[inserted.id] = inserted
        elif operation.op == "remove":
            from flowops.core.expressions import references

            if node.action in {"core.start", "core.end"} or any(
                ref.startswith(f"nodes.{node.id}.")
                for other in edited.nodes
                if other.id != node.id
                for ref in references(other.config)
            ):
                raise WorkflowValidationError(
                    "Não remova Início/Fim ou uma etapa cuja saída ainda é utilizada. Revise os vínculos primeiro."
                )
            edited.nodes.remove(node)
            edited.edges = [
                edge for edge in edited.edges if node.id not in {edge.source, edge.target}
            ]
            nodes.pop(node.id)
            changed.discard(node.id)
        elif operation.op == "position":
            value = operation.value
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(
                    type(part) not in {int, float} or abs(part) > 100000 or not math.isfinite(part)
                    for part in value
                )
            ):
                raise WorkflowValidationError("Posição inválida no canvas.")
            node.position = (value[0], value[1])
        elif operation.op == "connect":
            edited = connect(edited, node.id, operation.target, operation.branch)
            nodes = {entry.id: entry for entry in edited.nodes}
        elif operation.op == "disconnect":
            matches = [
                edge
                for edge in edited.edges
                if (edge.source, edge.target, edge.branch)
                == (node.id, operation.target, operation.branch)
            ]
            if not matches:
                raise WorkflowValidationError("A conexão já mudou. Atualize o canvas.")
            edited.edges.remove(matches[0])
        elif operation.op == "bind":
            schema = (
                registry.get(node.action).metadata.input_schema
                if not node.action.startswith("core.")
                else {}
            )
            targets = {
                field.path: field.type for field in flatten_schema(schema) if field.path != "$"
            }
            # Existing nested properties may have schema 'any'; preserve their exact path.
            for field in editable_fields(node.config):
                if all(isinstance(part, str) for part in field["path"]):
                    targets.setdefault(".".join(field["path"]), "any")
            source = next(
                (
                    field
                    for field in authoring_sources(edited, node.id, registry)
                    if field.path == operation.source
                ),
                None,
            )
            if source is None or operation.target not in targets:
                raise WorkflowValidationError(
                    "Selecione portas de origem e destino disponíveis nesta etapa."
                )
            reference_value(source, "", targets[operation.target])
            node.config = apply_mapping(node.config, operation.target, source.path)
            changed.add(node.id)
    for node_id in changed:
        _validate_references(edited, nodes[node_id], nodes[node_id].config, registry)
    return edited


def editor_data(book: Runbook, revision: int, registry: Any) -> dict[str, Any]:
    from flowops.core.expressions import EXPRESSION
    from flowops.core.graph import LOGIC_REQUIRED
    from flowops.streamlit.localization import action_label

    nodes: list[dict[str, Any]] = []
    for node in book.nodes:
        metadata = (
            registry.get(node.action).metadata if not node.action.startswith("core.") else None
        )
        schema = metadata.input_schema if metadata else {}
        sources = authoring_sources(book, node.id, registry)
        targets = [
            {"path": field.path, "type": field.type}
            for field in flatten_schema(schema)
            if field.path != "$"
        ]
        known_targets = {field["path"] for field in targets}
        for field in editable_fields(node.config):
            if all(isinstance(part, str) for part in field["path"]):
                path = ".".join(field["path"])
                if path not in known_targets:
                    targets.append({"path": path, "type": "any"})
        output_fields = flatten_schema(metadata.output_schema) if metadata else []
        outputs = [
            {
                "path": f"nodes.{node.id}.output" + ("." + field.path if field.path != "$" else ""),
                "type": field.type,
            }
            for field in output_fields
        ]
        if node.action in {"core.map", "core.filter", "core.for_each"}:
            outputs = [{"path": f"nodes.{node.id}.output.items", "type": "array"}]
        nodes.append(
            {
                "id": node.id,
                "position": {"x": node.position[0], "y": node.position[1]},
                "type": "flowops",
                "data": {
                    "label": node.label or node.id,
                    "action": node.action,
                    "branches": branch_options(book, node.id),
                    "config_json": json.dumps(node.config, ensure_ascii=False, indent=2),
                    "fields": editable_fields(node.config),
                    "targets": targets,
                    "outputs": outputs,
                    "sources": [
                        {
                            "path": source.path,
                            "type": source.type,
                            "label": source_label(book, source),
                        }
                        for source in sources
                    ],
                },
            }
        )
    ports = {node["id"]: node["data"] for node in nodes}
    data_edges: list[dict[str, Any]] = []
    for node in book.nodes:
        visible_targets = {field["path"] for field in ports[node.id]["targets"][:4]}
        for field in editable_fields(node.config):
            value = field["value"]
            match = EXPRESSION.fullmatch(value.strip()) if isinstance(value, str) else None
            path = ".".join(str(part) for part in field["path"])
            if match and path in visible_targets:
                source = match.group(1).strip()
                parts = source.split(".")
                if (
                    len(parts) >= 3
                    and parts[0] == "nodes"
                    and parts[1] in ports
                    and source in {output["path"] for output in ports[parts[1]]["outputs"][:4]}
                ):
                    data_edges.append(
                        {
                            "id": f"data-{len(data_edges)}",
                            "source": parts[1],
                            "target": node.id,
                            "sourceHandle": "data:" + source,
                            "targetHandle": "data:" + path,
                        }
                    )
    return {
        "protocol": 1,
        "book_id": book.id,
        "revision": revision,
        "base": digest(book.model_dump()),
        "nodes": nodes,
        "data_edges": data_edges,
        "name": book.name,
        "actions": [
            {"id": action, "label": action_label(action)}
            for action in sorted(
                set(LOGIC_REQUIRED) | {metadata.id for metadata in registry.list()}
            )
            if action not in {"core.start", "core.end"}
        ],
        "edges": [
            {
                "id": f"edge-{index}",
                "source": edge.source,
                "target": edge.target,
                "sourceHandle": "execution-out",
                "targetHandle": "execution-in",
                "label": edge.branch,
            }
            for index, edge in enumerate(book.edges)
        ],
    }


def render_react_editor(ui: Any, book: Runbook, revision: int) -> tuple[Runbook, str | None]:
    import streamlit as st
    import streamlit.components.v1 as components

    key = f"flowops:react:{book.id}"
    data = editor_data(book, revision, ui.runtime.registry)
    data["readonly"] = not ui._granted("runbook.edit", book)
    data["pending"] = st.session_state.get(key + ":pending")
    component = components.declare_component(
        "flowops_editor", path=str(Path(__file__).with_name("flow_editor_assets"))
    )
    response = component(data=data, key=key, default=None)
    if not isinstance(response, dict) or response.get("event_id") == st.session_state.get(
        key + ":last"
    ):
        return book, None
    st.session_state[key + ":last"] = response.get("event_id")
    try:
        if len(json.dumps(response)) > 250_000:
            raise WorkflowValidationError("A alteração excede o limite do editor.")
        command = Command.model_validate(response)
        if command.book_id != book.id or command.revision != revision:
            raise WorkflowValidationError("Mensagem de outra revisão; reabra o canvas.")
        if command.kind == "select":
            if command.operations:
                require(ui.user, "runbook.edit", book)
                st.session_state[key + ":pending"] = response | {"kind": "draft"}
            return book, command.selected if command.selected in {
                node.id for node in book.nodes
            } else None
        require(ui.user, "runbook.edit", book)
        if command.kind == "discard":
            st.session_state.pop(key + ":pending", None)
        elif command.kind == "draft":
            st.session_state[key + ":pending"] = response
        else:
            for node in book.nodes:
                buffer = st.session_state.get(f"flowops:visual:{book.id}:{node.id}:{node.action}")
                if isinstance(buffer, EditBuffer) and not buffer.pristine():
                    raise WorkflowValidationError(
                        "Aplique ou descarte os campos pendentes do formulário antes de aplicar o canvas."
                    )
            edited = apply_command(book, revision, response, ui.user, ui.runtime.registry)
            ui._store_working(edited, revision)
            st.session_state.pop(key + ":pending", None)
            st.rerun()
    except (FlowOpsError, ValidationError) as exc:
        render_error(exc)
    return book, None
