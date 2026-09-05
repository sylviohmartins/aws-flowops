"""Python-only contract around the third-party canvas; only layout/edges cross back.

The browser cannot inject action configuration or identity. Domain validation still runs
on publication/execution. Keep widget state stable across reruns to avoid v1.6.1 loops.
"""

import html
import math
from typing import Any

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Runbook
from flowops.persistence.repository import digest


def apply_canvas(book: Runbook, payload: dict[str, Any], *, readonly: bool = False) -> tuple[Runbook, str | None]:
    if readonly:
        return book.model_copy(deep=True), None
    result = book.model_copy(deep=True)
    known = {node.id: node for node in result.nodes}
    received = payload.get("nodes", [])
    if len(received) > 200 or len(payload.get("edges", [])) > 1000:
        raise WorkflowValidationError("Canvas size limit exceeded.")
    ids: set[str] = set()
    for entry in received:
        node_id = entry["id"]
        if node_id not in known or node_id in ids:
            raise WorkflowValidationError("Add or duplicate nodes using the action catalog.")
        ids.add(node_id)
        position = entry.get("position", {})
        x, y = float(position.get("x", 0)), float(position.get("y", 0))
        if not math.isfinite(x) or not math.isfinite(y) or abs(x) > 100000 or abs(y) > 100000:
            raise WorkflowValidationError("Invalid canvas position.")
        known[node_id].position = (x, y)
    result.nodes = [n for n in result.nodes if n.id in ids]
    result.edges = [Edge(source=e["source"], target=e["target"], branch=e.get("label") or "default") for e in payload.get("edges", [])]
    if any(e.source not in ids or e.target not in ids for e in result.edges):
        raise WorkflowValidationError("Canvas connection refers to a removed node.")
    selected = payload.get("selected_id")
    return result, selected if selected in ids else None


def workflow_canvas(book: Runbook, *, key: str = "workflow", readonly: bool = False, statuses: dict[str, str] | None = None) -> tuple[Runbook, str | None]:
    import streamlit as st
    from streamlit_flow import streamlit_flow
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
    from streamlit_flow.state import StreamlitFlowState

    state_key, hash_key = f"{key}:state", f"{key}:hash"
    fingerprint = digest({"book": book.model_dump(), "readonly": readonly, "statuses": statuses or {}})
    if state_key not in st.session_state or st.session_state.get(hash_key) != fingerprint:
        nodes = [StreamlitFlowNode(
            id=node.id, pos=node.position,
            data={"content": html.escape(f"{node.label or node.id}\n{node.action}\n{(statuses or {}).get(node.id, '')}")},
            node_type="input" if node.action == "core.start" else "output" if node.action == "core.end" else "default",
            draggable=not readonly, selectable=True, connectable=not readonly, deletable=not readonly,
            style={"border": "1px solid #94a3b8", "borderRadius": "8px", "background": "#ffffff" if node.enabled else "#e2e8f0", "color": "#0f172a", "width": 190},
        ) for node in book.nodes]
        edges = [StreamlitFlowEdge(id=f"e{i}", source=e.source, target=e.target, label=e.branch, marker_end={"type": "arrowclosed"}, deletable=not readonly) for i, e in enumerate(book.edges)]
        st.session_state[state_key] = StreamlitFlowState(nodes, edges)
        st.session_state[hash_key] = fingerprint
    state = streamlit_flow(key, st.session_state[state_key], height=560, fit_view=True, show_minimap=True, allow_new_edges=not readonly, get_node_on_click=True, enable_edge_menu=not readonly, enable_node_menu=False)
    st.session_state[state_key] = state
    result, selected = apply_canvas(book, state.asdict(), readonly=readonly)
    st.session_state[hash_key] = digest({"book": result.model_dump(), "readonly": readonly, "statuses": statuses or {}})
    return result, selected
