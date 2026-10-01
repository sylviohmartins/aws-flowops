"""Lossless, session-only editing primitives. No transport or execution side effects."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from flowops.core.expressions import EXPRESSION, path_parts
from flowops.core.mapping import SchemaField, source_fields
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook

KINDS = {
    "string": "Texto",
    "integer": "Inteiro",
    "number": "Número decimal",
    "boolean": "Sim ou não",
    "object": "Objeto (campos)",
    "array": "Lista",
    "null": "Nulo",
    "reference": "Valor de outra origem",
}


def value_kind(value: Any) -> str:
    if isinstance(value, str):
        return "reference" if EXPRESSION.fullmatch(value.strip()) else "string"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "object" if isinstance(value, dict) else "array"


def empty_value(kind: str) -> Any:
    return copy.deepcopy(
        {
            "string": "",
            "integer": 0,
            "number": 0.0,
            "boolean": False,
            "object": {},
            "array": [],
            "null": None,
            "reference": "",
        }[kind]
    )


def same_json(left: Any, right: Any) -> bool:
    """Compare JSON without Python's bool/int/float equality coercions."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            same_json(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass
class EditBuffer:
    """Widget state can expire on navigation; this buffer must not.

    Epochs advance only on explicit structure/mode application, never from a config digest.
    A divergent canonical value is a conflict, not permission to overwrite either copy.
    """

    base: dict[str, Any]
    value: dict[str, Any]
    raw: str
    epoch: int = 0
    mode: str = "Visual"
    kinds: dict[tuple[str | int, ...], str] = field(default_factory=dict)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def create(cls, value: dict[str, Any]) -> EditBuffer:
        return cls(
            copy.deepcopy(value),
            copy.deepcopy(value),
            json.dumps(value, ensure_ascii=False, indent=2),
        )

    def at(self, path: tuple[str | int, ...]) -> Any:
        value: Any = self.value
        for part in path:
            value = value[part]
        return value

    def put(self, path: tuple[str | int, ...], value: Any) -> None:
        parent = self.at(path[:-1])
        parent[path[-1]] = copy.deepcopy(value)

    def structural_change(self) -> None:
        self.epoch += 1
        self.kinds.clear()

    def parse_code(self) -> dict[str, Any]:
        def invalid_constant(_: str) -> Any:
            raise ValueError("Non-finite JSON number")

        try:
            value = json.loads(self.raw, parse_constant=invalid_constant)
            json.dumps(value, allow_nan=False)
        except (ValueError, RecursionError) as exc:
            raise WorkflowValidationError(
                "JSON inválido. Seu texto foi mantido; corrija antes de aplicar."
            ) from exc
        if not isinstance(value, dict):
            raise WorkflowValidationError("A configuração precisa ser um objeto JSON.")
        return value

    def pristine(self) -> bool:
        if self.parameters:
            return False
        try:
            return same_json(
                self.parse_code() if self.mode == "Editar JSON" else self.value, self.base
            )
        except WorkflowValidationError:
            return False

    def candidate(self, current: dict[str, Any]) -> dict[str, Any]:
        if not same_json(self.base, current):
            raise WorkflowValidationError(
                "A configuração mudou fora deste editor. Seu conteúdo foi preservado. "
                "Copie o que deseja manter antes de carregar a configuração atual."
            )
        return self.parse_code() if self.mode == "Editar JSON" else copy.deepcopy(self.value)

    def switch(self, mode: str) -> None:
        if self.mode == "Editar JSON" and mode != "Editar JSON":
            self.value = self.parse_code()
        if mode == "Editar JSON" and self.mode != mode:
            self.raw = json.dumps(self.value, ensure_ascii=False, indent=2)
        self.mode = mode
        self.structural_change()


def authoring_sources(book: Runbook, node_id: str, registry: Any) -> list[SchemaField]:
    fields = source_fields(book, node_id, registry)
    nodes = {node.id: node for node in book.nodes}
    for source in list(fields):
        parts = source.path.split(".")
        if len(parts) == 3 and parts[0] == "nodes":
            ancestor = nodes[parts[1]]
            if ancestor.action in {"core.map", "core.filter", "core.for_each"}:
                fields.append(SchemaField(source.path + ".items", "array"))
    return fields


def source_label(book: Runbook, source: SchemaField) -> str:
    """Keep technical paths in the contract, while making choices task-oriented."""
    parts = source.path.split(".")
    if parts[0] == "params":
        spec = book.parameters.get(parts[1])
        return f"Parâmetro · {spec.description or parts[1]} ({parts[1]})" if spec else source.path
    if parts[0] == "context":
        return "Contexto · " + {
            "account": "Conta AWS",
            "region": "Região",
            "environment": "Ambiente",
            "execution_id": "Identificador da execução",
        }.get(parts[1], parts[1])
    if parts[0] == "nodes":
        node = next((node for node in book.nodes if node.id == parts[1]), None)
        return f"Resultado · {node.label or node.id if node else parts[1]} · {'.'.join(parts[3:]) or 'saída completa'}"
    return "Item atual da lista" if source.path == "item" else source.path


def reference_value(source: SchemaField, suffix: str, target: str) -> str:
    path = source.path + ("." + suffix.strip() if suffix.strip() else "")
    path_parts(path)
    kind = "any" if suffix else source.type
    if (
        target != "any"
        and kind != "any"
        and kind != target
        and not (kind == "integer" and target == "number")
    ):
        raise WorkflowValidationError(
            f"Tipos incompatíveis: {KINDS.get(kind, kind)} → {KINDS.get(target, target)}."
        )
    if suffix and source.type not in {"object", "any"}:
        raise WorkflowValidationError(
            "Selecione a lista inteira para mapear cada item; não há seleção automática do primeiro item."
        )
    return "{{ " + path + " }}"


def pending_buffers(book: Runbook, session: Any) -> list[str]:
    """Only buffers for current nodes/parameters can prevent a save or publication."""
    entries = [(node.id, node.action) for node in book.nodes] + [("parameters", "core.parameters")]
    pending = []
    if session.get(f"flowops:react:{book.id}:pending"):
        pending.append("canvas avançado")
    for node_id, action in entries:
        value = session.get(f"flowops:visual:{book.id}:{node_id}:{action}")
        if isinstance(value, EditBuffer) and not value.pristine():
            pending.append("parâmetros" if action == "core.parameters" else node_id)
    return pending


def require_applied_buffers(book: Runbook, session: Any) -> None:
    if pending_buffers(book, session):
        raise WorkflowValidationError(
            "Há campos ainda não aplicados. Volte às etapas indicadas e aplique a configuração antes de salvar ou publicar."
        )
