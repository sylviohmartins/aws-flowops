"""Failure-path editor controls kept separate from the general workspace rendering."""

from __future__ import annotations

from flowops.domain.errors import FlowOpsError
from flowops.domain.models import Edge, Node, Runbook
from flowops.streamlit.workspace import FlowOpsWorkspaceUI


class FlowOpsGovernedUI(FlowOpsWorkspaceUI):
    """Add explicit failure-edge configuration for nodes using FAIL_BRANCH."""

    def _editor(self) -> None:
        import streamlit as st

        super()._editor()
        selected_id = st.session_state.get("flowops:selected_runbook")
        if not isinstance(selected_id, str):
            return
        try:
            persisted, revision = self.repository.get_draft(selected_id)
        except FlowOpsError:
            return
        working = self._working_draft(persisted, revision)
        selected_node_id = st.session_state.get(f"flowops:node:{persisted.id}")
        node = next((entry for entry in working.nodes if entry.id == selected_node_id), None)
        if node is None or node.failure_policy != "FAIL_BRANCH":
            return
        if not st.session_state.get(f"flowops:node-dialog:{persisted.id}"):
            self._failure_tools(working, node, revision)

    def _node_tools(self, working: Runbook, node: Node, revision: int) -> None:
        super()._node_tools(working, node, revision)
        if node.failure_policy == "FAIL_BRANCH":
            self._failure_tools(working, node, revision)

    def _failure_tools(self, working: Runbook, node: Node, revision: int) -> None:
        import streamlit as st

        persisted = working
        candidates = [
            entry for entry in working.nodes if entry.id != node.id and entry.action != "core.start"
        ]
        if not candidates:
            st.error("O tratamento FAIL_BRANCH exige outra etapa como destino do caminho de falha.")
            return
        current = next(
            (
                edge.target
                for edge in working.edges
                if edge.source == node.id and edge.branch == "failure"
            ),
            None,
        )
        ids = [entry.id for entry in candidates]
        index = ids.index(current) if current in ids else 0
        st.subheader("Caminho de falha")
        st.caption(
            "A conexão de falha deve ser definida explicitamente. Direcione-a para recuperação ou notificação; use uma etapa core.compensation quando for necessária uma ação compensatória na AWS."
        )
        target = st.selectbox(
            "Destino da falha",
            ids,
            index=index,
            format_func=lambda node_id: next(
                f"{entry.label or entry.id} · {entry.action}"
                for entry in candidates
                if entry.id == node_id
            ),
            key=f"flowops:failure-target:{persisted.id}:{node.id}",
        )
        editable = self._granted("runbook.edit", working)
        if st.button(
            "Aplicar caminho de falha",
            disabled=not editable,
            key=f"flowops:failure-apply:{persisted.id}:{node.id}",
        ):
            working.edges = [
                edge
                for edge in working.edges
                if not (edge.source == node.id and edge.branch == "failure")
            ]
            working.edges.append(Edge(source=node.id, target=target, branch="failure"))
            self._store_working(working, revision)
            st.rerun()
