"""Table/JSON inspection of bounded and sanitized execution results."""

from __future__ import annotations

import json
from typing import Any


def _attribute(value: Any) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        return value
    kind, payload = next(iter(value.items()))
    if kind in {"S", "N", "BOOL", "SS", "NS", "B", "BS"}:
        return payload
    if kind == "NULL":
        return None
    if kind == "M" and isinstance(payload, dict):
        return {key: _attribute(item) for key, item in payload.items()}
    if kind == "L" and isinstance(payload, list):
        return [_attribute(item) for item in payload]
    return value


def result_rows(output: Any, action: str = "") -> list[dict[str, Any]]:
    """Turn common provider envelopes into a bounded table-friendly shape."""
    value = output
    if isinstance(value, dict):
        if value.get("_truncated"):
            return []
        for key in (
            "Items",
            "Item",
            "Attributes",
            "Messages",
            "Payload",
            "Body",
            "items",
            "batches",
        ):
            if key in value:
                value = value[key]
                break
    entries = value if isinstance(value, list) else [value]
    rows: list[dict[str, Any]] = []
    for entry in entries[:1000]:
        row = entry if isinstance(entry, dict) else {"value": entry}
        if action.startswith("dynamodb."):
            row = {key: _attribute(item) for key, item in row.items()}
        rows.append(
            {
                str(key): json.dumps(item, ensure_ascii=False)
                if isinstance(item, (dict, list))
                else item
                for key, item in row.items()
            }
        )
    return rows


def render_output(output: Any, *, action: str, key: str) -> None:
    import streamlit as st

    mode = st.radio("Result format", ["Table", "JSON"], horizontal=True, key=f"{key}:format")
    rows = result_rows(output, action)
    if mode == "Table" and rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption("Table view preserves DynamoDB decimal strings and nested JSON values.")
    else:
        st.json(output, expanded=False)
    st.download_button(
        "Download result JSON",
        json.dumps(output, ensure_ascii=False, indent=2),
        file_name="flowops-result.json",
        mime="application/json",
        key=f"{key}:download",
    )


def render_results(execution: Any, node_details: dict[str, Any]) -> None:
    import streamlit as st

    available = [
        node_id for node_id, detail in node_details.items() if detail.get("output") is not None
    ]
    if not available:
        return
    st.subheader("Inspect node result")
    key = f"flowops:results:{execution.id}"
    selected = st.selectbox("Result node", available, key=f"{key}:node")
    node = next((node for node in execution.snapshot.nodes if node.id == selected), None)
    action = str(node.config.get("action", node.action)) if node else ""
    render_output(node_details[selected]["output"], action=action, key=f"{key}:{selected}")
