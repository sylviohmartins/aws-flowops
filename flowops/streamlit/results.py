"""Table/JSON inspection of bounded and sanitized execution results."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from flowops.streamlit.localization import display


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


def result_csv(rows: list[dict[str, Any]]) -> str:
    """Spreadsheet-safe CSV: neutralize formula-like strings at export."""
    output = io.StringIO(newline="")
    fields = list(dict.fromkeys(name for row in rows for name in row))
    writer = csv.writer(output)

    def safe(value: Any) -> Any:
        return (
            "'" + value
            if isinstance(value, str)
            and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
            else value
        )

    writer.writerow([safe(name) for name in fields])
    writer.writerows([safe(row.get(name, "")) for name in fields] for row in rows)
    return output.getvalue()


def render_output(output: Any, *, action: str, key: str, node_id: str = "node") -> None:
    import streamlit as st

    mode = st.radio(
        "Formato do resultado", ["Tabela", "JSON"], horizontal=True, key=f"{key}:format"
    )
    rows = result_rows(output, action)
    if mode == "Tabela" and rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "A tabela preserva valores decimais do DynamoDB como texto e estruturas JSON aninhadas."
        )
    else:
        st.json(output, expanded=False)
    st.download_button(
        "Baixar resultado em JSON",
        json.dumps(output, ensure_ascii=False, indent=2),
        file_name=f"{node_id}-result.json",
        mime="application/json",
        key=f"{key}:download",
    )
    if rows:
        st.download_button(
            "Baixar resultado em CSV",
            result_csv(rows),
            file_name=f"{node_id}-result.csv",
            mime="text/csv",
            key=f"{key}:csv",
        )


def render_results(
    execution: Any, node_details: dict[str, Any], *, selected_node: str | None = None
) -> None:
    import streamlit as st

    available = list(node_details)
    if not available:
        return
    st.subheader("Inspecionar resultado da etapa")
    key = f"flowops:results:{execution.id}"
    previous = st.session_state.get(f"{key}:canvas-selection")
    if selected_node in available and selected_node != previous:
        st.session_state[f"{key}:node"] = selected_node
    # A canvas remount can emit None before replaying its last selection. Only a
    # different concrete selection is a new click; preserve keyboard choice across it.
    if selected_node in available:
        st.session_state[f"{key}:canvas-selection"] = selected_node
    selected = st.selectbox("Etapa do resultado", available, key=f"{key}:node")
    node = next((node for node in execution.snapshot.nodes if node.id == selected), None)
    action = str(node.config.get("action", node.action)) if node else ""
    detail = node_details[selected]
    if detail.get("output") is not None:
        render_output(detail["output"], action=action, key=f"{key}:{selected}", node_id=selected)
    else:
        st.info(
            f"Esta etapa ainda não produziu saída. Estado: {display(detail.get('status', 'PENDING'))}."
        )
    st.download_button(
        "Baixar diagnóstico do nó (JSON)",
        json.dumps(detail, ensure_ascii=False, indent=2),
        file_name=f"{selected}-checkpoint.json",
        mime="application/json",
        key=f"{key}:{selected}:checkpoint",
    )
