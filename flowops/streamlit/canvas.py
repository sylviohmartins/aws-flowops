"""Python-only contract around the third-party canvas; only layout/edges cross back.

The browser cannot inject action configuration or identity. Domain validation still runs
on publication/execution. Keep widget state stable across reruns to avoid v1.6.1 loops.
"""

import html
import math
from typing import Any

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Runbook, new_id
from flowops.persistence.repository import digest
from flowops.streamlit.localization import CORE_LABELS, display

STATUS_COLORS = {
    "SUCCESS": "#15803d",
    "FAILED": "#dc2626",
    "RUNNING": "#2563eb",
    "WAITING_APPROVAL": "#b45309",
    "CANCELLED": "#64748b",
    "SKIPPED": "#94a3b8",
}


def edge_visual(edge: Edge, statuses: dict[str, str], branches: dict[str, str]) -> dict[str, Any]:
    """Match engine branch semantics; untraversed branches must not look successful."""
    source, target = statuses.get(edge.source), statuses.get(edge.target)
    active = (
        source == "SUCCESS"
        and edge.branch != "failure"
        and (edge.branch == "default" or branches.get(edge.source) == edge.branch)
    ) or (source == "FAILED" and edge.branch == branches.get(edge.source) == "failure")
    reached = active and target not in {None, "PENDING", "SKIPPED"}
    color = STATUS_COLORS.get(target or "", "#94a3b8") if reached else "#cbd5e1"
    return {
        "animated": bool(reached and target == "RUNNING"),
        "style": {"stroke": color, "strokeWidth": 3 if reached else 1.5},
        "marker_end": {"type": "arrowclosed", "color": color},
    }


def apply_canvas(
    book: Runbook, payload: dict[str, Any], *, readonly: bool = False
) -> tuple[Runbook, str | None]:
    if readonly:
        selected = payload.get("selected_id")
        return book.model_copy(deep=True), selected if selected in {
            n.id for n in book.nodes
        } else None
    result = book.model_copy(deep=True)
    known = {node.id: node for node in result.nodes}
    received = payload.get("nodes", [])
    if len(received) > 200 or len(payload.get("edges", [])) > 1000:
        raise WorkflowValidationError("O fluxo excedeu o limite de tamanho.")
    ids: set[str] = set()
    for entry in received:
        node_id = entry["id"]
        if node_id not in known or node_id in ids:
            raise WorkflowValidationError("Adicione ou duplique etapas usando o catálogo de ações.")
        ids.add(node_id)
        position = entry.get("position", {})
        x, y = float(position.get("x", 0)), float(position.get("y", 0))
        if not math.isfinite(x) or not math.isfinite(y) or abs(x) > 100000 or abs(y) > 100000:
            raise WorkflowValidationError("Posição inválida na área do fluxo.")
        known[node_id].position = (x, y)
    result.nodes = [n for n in result.nodes if n.id in ids]
    result.edges = [
        Edge(source=e["source"], target=e["target"], branch=e.get("label") or "default")
        for e in payload.get("edges", [])
    ]
    if any(e.source not in ids or e.target not in ids for e in result.edges):
        raise WorkflowValidationError("Uma conexão do fluxo aponta para uma etapa removida.")
    selected = payload.get("selected_id")
    return result, selected if selected in ids else None


def duplicate_node(book: Runbook, node_id: str) -> tuple[Runbook, str]:
    """Copy definition and layout without inventing execution edges."""
    result = book.model_copy(deep=True)
    source = next((node for node in result.nodes if node.id == node_id), None)
    if source is None or source.action in {"core.start", "core.end"}:
        raise WorkflowValidationError("Selecione uma etapa de ação ou de lógica para duplicar.")
    if len(result.nodes) >= 200:
        raise WorkflowValidationError("O fluxo excedeu o limite de tamanho.")
    clone = source.model_copy(deep=True)
    clone.id = f"n_{new_id()[:12]}"
    clone.label = f"{source.label or source.id} (cópia)"[:120]
    clone.position = (source.position[0] + 40, source.position[1] + 100)
    result.nodes.append(clone)
    return result, clone.id


def workflow_canvas(
    book: Runbook,
    *,
    key: str = "workflow",
    readonly: bool = False,
    statuses: dict[str, str] | None = None,
    branches: dict[str, str] | None = None,
) -> tuple[Runbook, str | None]:
    import streamlit as st
    from streamlit_flow import streamlit_flow
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
    from streamlit_flow.state import StreamlitFlowState

    state_key, hash_key, revision_key = f"{key}:state", f"{key}:hash", f"{key}:revision"
    fingerprint = digest(
        {
            "book": book.model_dump(),
            "readonly": readonly,
            "statuses": statuses or {},
            "branches": branches or {},
        }
    )
    if state_key not in st.session_state or st.session_state.get(hash_key) != fingerprint:
        nodes = [
            StreamlitFlowNode(
                id=node.id,
                pos=node.position,
                source_position="right",
                target_position="left",
                data={
                    "content": html.escape(
                        f"{display(node.label) if node.label else CORE_LABELS.get(node.action.removeprefix('core.'), node.id)}\n\n{'' if node.label == node.action else node.action}\n\n{display((statuses or {}).get(node.id, ''))}"
                    )
                },
                node_type="input"
                if node.action == "core.start"
                else "output"
                if node.action == "core.end"
                else "default",
                draggable=not readonly,
                selectable=True,
                connectable=not readonly,
                deletable=not readonly,
                style={
                    "border": f"2px solid {STATUS_COLORS.get((statuses or {}).get(node.id, ''), '#94a3b8')}",
                    "borderRadius": "8px",
                    "background": "#ffffff" if node.enabled else "#e2e8f0",
                    "color": "#0f172a",
                    "width": 190,
                },
            )
            for node in book.nodes
        ]
        edges = [
            StreamlitFlowEdge(
                id=f"e{i}",
                source=e.source,
                target=e.target,
                label=e.branch,
                **edge_visual(e, statuses or {}, branches or {}),
                deletable=not readonly,
            )
            for i, e in enumerate(book.edges)
        ]
        st.session_state[state_key] = StreamlitFlowState(nodes, edges)
        st.session_state[hash_key] = fingerprint
        # v1.6.1 returns the previous widget value while applying new Python props.
        # A new widget identity prevents that stale graph from deleting new nodes.
        # Browser layout/selection changes retain this revision and the same iframe.
        st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
    state = streamlit_flow(
        f"{key}:{st.session_state[revision_key]}",
        st.session_state[state_key],
        height=560,
        fit_view=True,
        min_zoom=0.1,
        show_minimap=True,
        allow_new_edges=not readonly,
        get_node_on_click=True,
        enable_edge_menu=not readonly,
        enable_node_menu=False,
    )
    st.session_state[state_key] = state
    result, selected = apply_canvas(book, state.asdict(), readonly=readonly)
    st.session_state[hash_key] = digest(
        {
            "book": result.model_dump(),
            "readonly": readonly,
            "statuses": statuses or {},
            "branches": branches or {},
        }
    )
    if len(result.edges) > len(book.edges):
        # New browser edges omit deletable/markers; normalize them on the next render.
        st.session_state.pop(hash_key, None)
    return result, selected
