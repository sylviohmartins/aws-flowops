"""Explicit resource discovery and DynamoDB query construction for node properties."""

from __future__ import annotations

from typing import Any

from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.providers.aws.query_builder import build_read, key_fields
from flowops.providers.aws.resources import EXPLORERS, explore, read_action, resource_choices


def _resource_field(service: str) -> str:
    return {
        "dynamodb": "TableName",
        "sqs": "QueueUrl",
        "sns": "TopicArn",
        "lambda": "FunctionName",
        "s3": "Bucket",
    }[service]


def _fingerprint(ui: Any, service: str, node_id: str) -> str:
    from flowops.persistence.repository import digest

    return digest({"context": ui.aws.model_dump(mode="json"), "service": service, "node": node_id})[
        :20
    ]


def _apply_resource(node: Any, service: str, selected: str) -> None:
    node.config[_resource_field(service)] = selected


def _render_dynamodb_query(
    ui: Any,
    book: Any,
    node: Any,
    revision: int,
    table_name: str,
    *,
    key: str,
) -> None:
    import streamlit as st

    describe_key = f"{key}:describe"
    if st.button("Load table schema", key=f"{key}:describe-button"):
        result = read_action(
            ui.runtime.registry,
            ui.user,
            ui.aws,
            "dynamodb.describe_table",
            {"TableName": table_name},
        )
        st.session_state[describe_key] = result.get("Table", result)
    table = st.session_state.get(describe_key)
    if not isinstance(table, dict):
        st.caption("Load the table schema to generate a bounded GetItem or Query request.")
        return
    st.dataframe(
        [
            {"field": field["name"], "type": field["type"], "role": field["key_type"]}
            for field in key_fields(table)
        ],
        width="stretch",
        hide_index=True,
    )
    operation = st.selectbox("DynamoDB read", ["get_item", "query"], key=f"{key}:operation")
    index_names = [""] + [
        entry["IndexName"]
        for entry in table.get("GlobalSecondaryIndexes", [])
        + table.get("LocalSecondaryIndexes", [])
        if isinstance(entry, dict) and isinstance(entry.get("IndexName"), str)
    ]
    index = st.selectbox(
        "Index (optional)",
        index_names,
        format_func=lambda value: value or "Table primary key",
        key=f"{key}:index",
    )
    fields = key_fields(table, index or "")
    values: dict[str, str] = {}
    for field in fields:
        values[field["name"]] = st.text_input(
            f"Key {field['name']} ({field['type']})",
            key=f"{key}:key:{field['name']}",
        )
    sort_operator = ""
    sort_end = ""
    if operation == "query" and any(field["key_type"] == "RANGE" for field in fields):
        sort_operator = st.selectbox(
            "Sort-key condition",
            ["", "=", ">=", "<=", "begins_with", "between"],
            key=f"{key}:sort-op",
        )
        if sort_operator == "between":
            sort_end = st.text_input("Sort-key upper bound", key=f"{key}:sort-end")
    limit = int(
        st.number_input(
            "Read limit", min_value=1, max_value=100, value=30, step=1, key=f"{key}:limit"
        )
    )
    if st.button("Apply generated DynamoDB request", key=f"{key}:apply-query"):
        generated = build_read(
            operation,
            table,
            values,
            index=index or "",
            sort_operator=sort_operator,
            sort_end=sort_end,
            limit=limit,
        )
        node.config = generated
        ui._store_working(book, revision)
        st.rerun()


def render_resource_picker(ui: Any, book: Any, node: Any, revision: int) -> None:
    """Render explicit, read-only discovery; mutations happen only on Apply buttons."""
    import streamlit as st

    service = node.action.split(".", 1)[0]
    if service not in EXPLORERS:
        return
    st.subheader("AWS resource discovery")
    st.caption(
        "Discovery calls only read APIs. The selected value is written to this node only after Apply."
    )
    key = f"flowops:resource-picker:{_fingerprint(ui, service, node.id)}"
    if st.button("Discover resources for this node", key=f"{key}:discover"):
        st.session_state[f"{key}:result"] = explore(ui.runtime.registry, ui.user, ui.aws, service)
    result = st.session_state.get(f"{key}:result")
    choices = resource_choices(service, result)
    if not choices:
        st.info(
            "No discovered resource is available yet; enter a literal value in Configuration JSON if needed."
        )
        return
    selected = st.selectbox("Discovered resource", choices, key=f"{key}:selected")
    if st.button(
        "Apply discovered resource",
        disabled=not ui._granted("runbook.edit", book),
        key=f"{key}:apply",
    ):
        _apply_resource(node, service, selected)
        ui._store_working(book, revision)
        st.rerun()
    if service == "dynamodb" and node.action in {"dynamodb.get_item", "dynamodb.query"}:
        try:
            _render_dynamodb_query(ui, book, node, revision, selected, key=key)
        except FlowOpsError as error:
            st.error(str(error))
        except (KeyError, TypeError, ValueError, WorkflowValidationError) as error:
            st.error(str(error))
