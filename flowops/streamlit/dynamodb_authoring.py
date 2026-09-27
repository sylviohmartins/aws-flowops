"""Lossless adapter for the supported DynamoDB read builder, without AWS calls."""

from __future__ import annotations

import copy
import re
from typing import Any

from flowops.core.expressions import EXPRESSION
from flowops.domain.errors import WorkflowValidationError
from flowops.providers.aws.query_builder import build_read, key_fields

SORT_EXPRESSIONS = {
    "": "",
    "=": " AND #sk = :sk",
    ">=": " AND #sk >= :sk",
    "<=": " AND #sk <= :sk",
    "begins_with": " AND begins_with(#sk, :sk)",
    "between": " AND #sk BETWEEN :sk AND :end",
}


def decode_read(operation: str, table: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "values": {},
        "index": config.get("IndexName", ""),
        "sort_operator": "",
        "sort_end": "",
        "limit": config.get("Limit", 30),
    }
    fields = key_fields(table, state["index"])
    if not config or not any(key in config for key in ("Key", "KeyConditionExpression")):
        return state
    if operation == "get_item":
        attributes = config.get("Key", {})
    else:
        expression = config.get("KeyConditionExpression")
        matched = [
            op for op, suffix in SORT_EXPRESSIONS.items() if expression == "#pk = :pk" + suffix
        ]
        if not matched:
            raise WorkflowValidationError(
                "Esta condição usa uma sintaxe avançada. Ela foi preservada: altere os campos pela Configuração visual ou pelo modo JSON, sem regenerar a consulta."
            )
        state["sort_operator"] = matched[0]
        names = config.get("ExpressionAttributeNames", {})
        values = config.get("ExpressionAttributeValues", {})
        attributes = {
            names[alias]: values.get(token)
            for alias, token in (("#pk", ":pk"), ("#sk", ":sk"))
            if alias in names
        }
        if ":end" in values:
            end = values[":end"]
            state["sort_end"] = (
                next(iter(end.values())) if isinstance(end, dict) and len(end) == 1 else None
            )
    for name, value in attributes.items():
        field = next((field for field in fields if field["name"] == name), None)
        if (
            field is None
            or not isinstance(value, dict)
            or list(value) != [field["type"]]
            or field["type"] not in {"S", "N"}
            or not isinstance(value[field["type"]], str)
        ):
            raise WorkflowValidationError(
                "A estrutura atual não corresponde às chaves S/N desta tabela ou índice. A configuração foi preservada; revise a tabela e use o editor de campos."
            )
        state["values"][name] = value[field["type"]]
    return state


def merge_read(current: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Replace only owned fields; shared aliases must not change another expression."""
    merged = copy.deepcopy(current)
    other_expressions = " ".join(
        value
        for key, value in current.items()
        if key.endswith("Expression") and key != "KeyConditionExpression" and isinstance(value, str)
    )
    used_elsewhere = set(re.findall(r"[#:][A-Za-z0-9_]+", other_expressions))
    old_key = set(re.findall(r"[#:][A-Za-z0-9_]+", str(current.get("KeyConditionExpression", ""))))
    for mapping in ("ExpressionAttributeNames", "ExpressionAttributeValues"):
        existing = copy.deepcopy(current.get(mapping, {}))
        for token, value in generated.get(mapping, {}).items():
            if token in used_elsewhere and token in existing and existing[token] != value:
                raise WorkflowValidationError(
                    "Um alias da chave também é usado em uma projeção ou filtro. Altere os campos avançados em conjunto; nada foi substituído."
                )
        for token in old_key - used_elsewhere:
            existing.pop(token, None)
        existing.update(generated.get(mapping, {}))
        if existing:
            merged[mapping] = existing
        else:
            merged.pop(mapping, None)
    for key in ("TableName", "Key", "KeyConditionExpression", "Limit", "IndexName"):
        merged.pop(key, None)
        if key in generated:
            merged[key] = copy.deepcopy(generated[key])
    for key, value in generated.items():
        if key not in merged and key not in {
            "ExpressionAttributeNames",
            "ExpressionAttributeValues",
        }:
            merged[key] = copy.deepcopy(value)
    return merged


def build_bound_read(
    operation: str,
    table: dict[str, Any],
    values: dict[str, str],
    *,
    current: dict[str, Any],
    index: str = "",
    sort_operator: str = "",
    sort_end: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    fields = key_fields(table, index)
    kinds = {field["name"]: field["type"] for field in fields}
    literals = {
        name: ("0" if kinds.get(name) == "N" else "binding")
        if EXPRESSION.fullmatch(value.strip())
        else value
        for name, value in values.items()
    }
    end_binding = bool(EXPRESSION.fullmatch(sort_end.strip()))
    generated = build_read(
        operation,
        table,
        literals,
        index=index,
        sort_operator=sort_operator,
        sort_end="0" if end_binding else sort_end,
        limit=limit,
    )
    if current and "ConsistentRead" not in current:
        generated.pop("ConsistentRead", None)
    if operation == "get_item":
        for name, value in values.items():
            if name in generated["Key"]:
                generated["Key"][name] = {kinds[name]: value}
    else:
        for alias, token in (("#pk", ":pk"), ("#sk", ":sk")):
            name = generated["ExpressionAttributeNames"].get(alias)
            if name:
                generated["ExpressionAttributeValues"][token] = {kinds[name]: values[name]}
        if end_binding and ":end" in generated["ExpressionAttributeValues"]:
            generated["ExpressionAttributeValues"][":end"] = {
                next(field["type"] for field in fields if field["key_type"] == "RANGE"): sort_end
            }
    if isinstance(current.get("TableName"), str) and EXPRESSION.fullmatch(
        current["TableName"].strip()
    ):
        generated["TableName"] = current["TableName"]
    merged = merge_read(current, generated)
    if merged.get("ConsistentRead") and any(
        entry.get("IndexName") == index for entry in table.get("GlobalSecondaryIndexes", [])
    ):
        raise WorkflowValidationError(
            "Índices globais não aceitam leitura consistente. Desative ConsistentRead nos campos antes de aplicar este índice."
        )
    return merged
