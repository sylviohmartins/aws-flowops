"""Bounded DynamoDB read request construction for the resource explorer."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from flowops.domain.errors import WorkflowValidationError


def key_fields(table: dict[str, Any], index: str = "") -> list[dict[str, str]]:
    """Return the selected table/index key schema with its DynamoDB types."""
    target = table
    if index:
        indexes = table.get("GlobalSecondaryIndexes", []) + table.get("LocalSecondaryIndexes", [])
        target = next(
            (
                entry
                for entry in indexes
                if isinstance(entry, dict) and entry.get("IndexName") == index
            ),
            {},
        )
    types: dict[str, str] = {
        entry["AttributeName"]: entry["AttributeType"]
        for entry in table.get("AttributeDefinitions", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("AttributeName"), str)
        and isinstance(entry.get("AttributeType"), str)
    }
    return [
        {
            "name": entry["AttributeName"],
            "type": types.get(entry["AttributeName"], "S"),
            "key_type": entry["KeyType"],
        }
        for entry in target.get("KeySchema", [])
        if isinstance(entry, dict)
        and entry.get("AttributeName") in types
        and entry.get("KeyType") in {"HASH", "RANGE"}
    ]


def _value(value: str, kind: str) -> dict[str, str]:
    if not value or kind not in {"S", "N"}:
        raise WorkflowValidationError(
            "Enter a non-empty string or numeric key; binary keys use advanced JSON."
        )
    if kind == "N":
        try:
            if not Decimal(value).is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError) as error:
            raise WorkflowValidationError("Numeric keys require a finite number.") from error
    return {kind: value}


def build_read(
    operation: str,
    table: dict[str, Any],
    values: dict[str, str],
    *,
    index: str = "",
    sort_operator: str = "",
    sort_end: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    """Build a literal GetItem/Query request with a hard result bound."""
    fields = key_fields(table, index)
    if not fields or operation not in {"get_item", "query"}:
        raise WorkflowValidationError("Choose a valid table/index and read operation.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise WorkflowValidationError("Read limit must be between 1 and 100.")
    for field in fields:
        value = values.get(field["name"])
        if value:
            _value(value, field["type"])
    if operation == "get_item":
        if index:
            raise WorkflowValidationError("GetItem uses the table primary key, not an index.")
        config: dict[str, Any] = {
            "TableName": table["TableName"],
            "Key": {
                field["name"]: _value(values.get(field["name"], ""), field["type"])
                for field in fields
            },
            "ConsistentRead": True,
        }
        return config

    partition = next((field for field in fields if field["key_type"] == "HASH"), None)
    if partition is None:
        raise WorkflowValidationError("Selected table/index has no partition key.")
    config = {
        "TableName": table["TableName"],
        "Limit": limit,
        "KeyConditionExpression": "#pk = :pk",
        "ExpressionAttributeNames": {"#pk": partition["name"]},
        "ExpressionAttributeValues": {
            ":pk": _value(values.get(partition["name"], ""), partition["type"])
        },
    }
    if index:
        config["IndexName"] = index
    sort = next((field for field in fields if field["key_type"] == "RANGE"), None)
    if sort and values.get(sort["name"]) and not sort_operator:
        raise WorkflowValidationError("Choose a sort-key condition for the supplied range key.")
    if sort_operator:
        if sort is None or sort_operator not in {"=", ">=", "<=", "begins_with", "between"}:
            raise WorkflowValidationError("Choose a supported sort-key condition.")
        if sort_operator == "begins_with" and sort["type"] != "S":
            raise WorkflowValidationError("begins_with requires a string sort key.")
        config["ExpressionAttributeNames"]["#sk"] = sort["name"]
        config["ExpressionAttributeValues"][":sk"] = _value(
            values.get(sort["name"], ""), sort["type"]
        )
        if sort_operator == "between":
            config["ExpressionAttributeValues"][":end"] = _value(sort_end, sort["type"])
            expression = "#sk BETWEEN :sk AND :end"
        elif sort_operator == "begins_with":
            expression = "begins_with(#sk, :sk)"
        else:
            expression = f"#sk {sort_operator} :sk"
        config["KeyConditionExpression"] += " AND " + expression
    return config
