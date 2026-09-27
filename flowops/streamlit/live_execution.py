"""Read-only execution polling, isolated from the submit form."""

from typing import Any

from flowops.core.policies import require
from flowops.domain.models import Status
from flowops.streamlit.canvas import workflow_canvas
from flowops.streamlit.localization import display, render_error
from flowops.streamlit.results import render_results


def render_live_execution(ui: Any, execution_id: str) -> None:
    import streamlit as st

    def view() -> None:
        # A timer callback from the previous Execute page may arrive after a
        # sidebar navigation rerun. It must not append stale execution UI to
        # the destination page or read a no-longer-valid execution context.
        current_page = st.session_state.get("flowops:navigation")
        if current_page is not None and current_page not in {"Execute", "Executions"}:
            return
        execution = ui.runtime.engine.store.get(execution_id)
        require(ui.user, "runbook.read", execution.snapshot)
        details = ui.runtime.engine.store.nodes(execution_id)
        statuses = {key: str(value.get("status", "PENDING")) for key, value in details.items()}
        branches = {key: str(value.get("branch", "default")) for key, value in details.items()}
        st.subheader("Execução ao vivo")
        st.caption(
            f"{execution.id} · {display(execution.status.value)} · atualização a cada 2 segundos"
        )
        st.caption(
            "Verde: sucesso · Azul animado: em execução · Âmbar: aprovação · Vermelho: erro · Cinza: não percorrido"
        )
        if execution.status == Status.WAITING_APPROVAL:
            st.warning(
                "Execução pausada. Abra Aprovações no menu, revise e registre a decisão para continuar."
            )
        if execution.error:
            render_error(execution.error)
        if execution.dry_run and any(
            node.action == "core.approval" for node in execution.snapshot.nodes
        ):
            st.info(
                "Simulação: as etapas de aprovação são simuladas. Nenhuma pendência manual é criada."
            )
        _, selected = workflow_canvas(
            execution.snapshot,
            key=f"flowops-live-{execution.id}",
            readonly=True,
            statuses=statuses,
            branches=branches,
        )
        st.caption(
            "Clique em uma caixa para inspecionar e baixar o resultado ou diagnóstico daquela etapa."
        )
        render_results(execution, details, selected_node=selected)

    # Small hosts/test doubles can render a snapshot; supported Streamlit uses timed fragments.
    fragment = getattr(st, "fragment", None)
    if callable(fragment):
        fragment(run_every=2)(view)()
    else:
        view()
