from __future__ import annotations

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.providers.aws.query_builder import build_read, key_fields

TABLE = {
    "TableName": "flowops-payments",
    "AttributeDefinitions": [
        {"AttributeName": "paymentId", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "updatedAt", "AttributeType": "N"},
    ],
    "KeySchema": [{"AttributeName": "paymentId", "KeyType": "HASH"}],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "status-index",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
        }
    ],
}


def test_key_fields_and_get_item_are_typed_and_literal() -> None:
    assert key_fields(TABLE) == [{"name": "paymentId", "type": "S", "key_type": "HASH"}]
    assert key_fields(TABLE, "status-index")[1]["type"] == "N"
    request = build_read("get_item", TABLE, {"paymentId": "PAY-1001"})
    assert request["Key"] == {"paymentId": {"S": "PAY-1001"}}
    assert request["ConsistentRead"] is True


def test_query_supports_bounded_sort_conditions() -> None:
    request = build_read(
        "query",
        TABLE,
        {"status": "PROCESSING", "updatedAt": "100"},
        index="status-index",
        sort_operator="between",
        sort_end="200",
        limit=25,
    )
    assert request["IndexName"] == "status-index"
    assert request["Limit"] == 25
    assert request["KeyConditionExpression"].endswith("#sk BETWEEN :sk AND :end")
    assert request["ExpressionAttributeValues"][":end"] == {"N": "200"}

    no_sort = build_read("query", TABLE, {"paymentId": "PAY-1001"}, limit=1)
    assert no_sort["KeyConditionExpression"] == "#pk = :pk"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation": "get_item", "index": "status-index"},
        {"operation": "query", "limit": 101},
        {"operation": "query", "values": {"status": ""}},
        {
            "operation": "query",
            "values": {"status": "P", "updatedAt": "x"},
            "index": "status-index",
        },
    ],
)
def test_invalid_read_builder_requests_fail_closed(kwargs: dict) -> None:
    values = kwargs.pop("values", {"paymentId": "PAY-1001", "status": "P", "updatedAt": "1"})
    with pytest.raises(WorkflowValidationError):
        build_read(values=values, table=TABLE, **kwargs)


def test_numeric_begins_with_is_not_allowed() -> None:
    with pytest.raises(WorkflowValidationError, match="begins_with"):
        build_read(
            "query",
            TABLE,
            {"status": "P", "updatedAt": "1"},
            index="status-index",
            sort_operator="begins_with",
        )


@pytest.mark.parametrize("operator", ["=", ">=", "<="])
def test_builder_supports_each_literal_sort_operator(operator: str) -> None:
    request = build_read(
        "query",
        TABLE,
        {"status": "P", "updatedAt": "1"},
        index="status-index",
        sort_operator=operator,
    )
    assert request["ExpressionAttributeValues"][":sk"] == {"N": "1"}


def test_builder_rejects_unknown_index_operation_and_non_finite_numbers() -> None:
    assert key_fields(TABLE, "missing") == []
    with pytest.raises(WorkflowValidationError):
        build_read("scan", TABLE, {})
    with pytest.raises(WorkflowValidationError):
        build_read("get_item", TABLE, {"paymentId": "x"}, index="missing")
    with pytest.raises(WorkflowValidationError, match="finite"):
        build_read("query", TABLE, {"status": "P", "updatedAt": "NaN"}, index="status-index")
    with pytest.raises(WorkflowValidationError, match="sort-key"):
        build_read(
            "query",
            TABLE,
            {"status": "P", "updatedAt": "1"},
            index="status-index",
            sort_operator="invalid",
        )
