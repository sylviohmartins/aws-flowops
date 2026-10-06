import copy

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.providers.aws.query_builder import build_read
from flowops.streamlit.dynamodb_authoring import build_bound_read, decode_read, merge_read
from tests.test_resource_picker import TABLE


@pytest.mark.parametrize("operation", ["query", "get_item"])
def test_read_roundtrip_retains_advanced_options_and_bindings(operation: str) -> None:
    base = build_read(operation, TABLE, {"status": "PROCESSING"})
    base["_flowops"] = {"paginate": True, "max_pages": 2}
    base["ProjectionExpression"] = "#projected"
    base.setdefault("ExpressionAttributeNames", {})["#projected"] = "paymentId"
    base["ReturnConsumedCapacity"] = "TOTAL"
    base["TableName"] = "{{ params.table_name }}"
    state = decode_read(operation, TABLE, base)
    result = build_bound_read(operation, TABLE, current=base, **state)
    assert result == base
    assert result is not base


def test_query_keeps_numeric_wire_text_and_preserves_aliases_or_refuses_collision() -> None:
    base = build_read(
        "query",
        TABLE,
        {"status": "PROCESSING", "updatedAt": "100"},
        index="status-index",
        sort_operator="between",
        sort_end="200",
    )
    base["FilterExpression"] = "#filter = :filter"
    base["ExpressionAttributeNames"]["#filter"] = "active"
    base["ExpressionAttributeValues"][":filter"] = {"BOOL": True}
    before = copy.deepcopy(base)
    state = decode_read("query", TABLE, base)
    state["values"]["updatedAt"] = "{{ params.since }}"
    result = build_bound_read("query", TABLE, current=base, **state)
    assert result["ExpressionAttributeValues"][":sk"] == {"N": "{{ params.since }}"}
    assert result["ExpressionAttributeValues"][":filter"] == {"BOOL": True}
    assert base == before
    base["FilterExpression"] = "#pk = :pk"
    state["values"]["status"] = "OTHER"
    with pytest.raises(WorkflowValidationError, match="alias"):
        build_bound_read("query", TABLE, current=base, **state)


def test_unknown_shapes_gsi_consistency_and_get_item_index_fail_without_loss() -> None:
    advanced = {
        "KeyConditionExpression": "id = :id",
        "ExpressionAttributeValues": {":id": {"S": "one"}},
    }
    with pytest.raises(WorkflowValidationError, match="avançada"):
        decode_read("query", TABLE, advanced)
    with pytest.raises(WorkflowValidationError, match="preservada"):
        decode_read("get_item", TABLE, {"Key": {"status": {"B": "YQ=="}}})
    with pytest.raises(WorkflowValidationError, match="globais"):
        build_bound_read(
            "query", TABLE, {"status": "P"}, current={"ConsistentRead": True}, index="status-index"
        )
    with pytest.raises(WorkflowValidationError, match="primary key"):
        build_bound_read("get_item", TABLE, {"status": "P"}, current={}, index="status-index")
    assert decode_read("query", TABLE, {})["values"] == {}
    assert merge_read(
        {
            "KeyConditionExpression": "#pk = :pk",
            "ExpressionAttributeNames": {"#pk": "id"},
            "ExpressionAttributeValues": {":pk": {"S": "one"}},
        },
        {"TableName": "table", "Key": {"id": {"S": "one"}}},
    ) == {"TableName": "table", "Key": {"id": {"S": "one"}}}
