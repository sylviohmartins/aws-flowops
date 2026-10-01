"""Contextual node editing. Values are applied only to the current session draft."""

from __future__ import annotations

import json
from typing import Any

from flowops.domain.errors import FlowOpsError
from flowops.domain.models import Node, Runbook
from flowops.streamlit.authoring import value_kind
from flowops.streamlit.localization import display, render_error
from flowops.streamlit.value_editor import render_config_editor

LOGIC_FIELDS: dict[str, dict[str, Any]] = {
    "core.approval": {"message": "Revise os dados antes de continuar"},
    "core.wait": {"seconds": 1},
    "core.validation": {
        "left": "{{ params.environment }}",
        "operator": "eq",
        "right": "{{ context.environment }}",
    },
    "core.condition": {"left": "", "operator": "eq", "right": ""},
    "core.switch": {"value": "", "cases": {}},
    "core.filter": {"items": [], "path": "status.S", "operator": "eq", "value": "PROCESSING"},
    "core.map": {"items": [], "template": {"payment_id": "{{ item.paymentId.S }}"}},
    "core.for_each": {"items": [], "template": {}},
    "core.batch": {"items": [], "size": 10},
    "core.merge": {"inputs": {}},
    "core.stop": {"reason": "Interrompido pelo procedimento"},
    "core.retry": {"action": "", "config": {}},
    "core.compensation": {"action": "", "config": {}},
}


def initial_config(action: str) -> dict[str, Any]:
    from flowops.streamlit.action_forms import recommended_config

    return recommended_config(action, json.loads(json.dumps(LOGIC_FIELDS.get(action, {}))))


def render_logic_inputs(ui: Any, book: Runbook, node: Node, revision: int) -> None:
    import streamlit as st

    fields = LOGIC_FIELDS.get(node.action)
    if not fields:
        return
    st.caption(
        "Selecione a lista de uma etapa anterior em Itens. Em Mapear itens, o Modelo define "
        "os campos de cada resultado: a origem Item representa um elemento da lista. "
        "Em Filtrar itens, informe o campo, o operador e o valor de comparação."
    )
    properties: dict[str, Any] = {
        name: {"type": value_kind(default), "default": default} for name, default in fields.items()
    }
    for name in {"left", "right", "value", "template", "inputs"} & properties.keys():
        properties[name]["type"] = "any"
    if "operator" in properties:
        properties["operator"]["enum"] = [
            "eq",
            "ne",
            "gt",
            "gte",
            "lt",
            "lte",
            "in",
            "contains",
            "exists",
            "truthy",
        ]
    render_config_editor(
        ui,
        book,
        node,
        revision,
        {"type": "object", "properties": properties},
        title="Configurar lógica",
    )


def dismiss_node(book_id: str) -> None:
    import streamlit as st

    st.session_state.pop(f"flowops:node-dialog:{book_id}", None)
    selected = st.session_state.get(f"flowops:node:{book_id}")
    if isinstance(selected, str):
        # streamlit-flow 1.6.1 can emit the previous selected_id once while a
        # new widget identity is replacing the old canvas. Mark only that echo
        # for suppression; a later real click on the same node must still work.
        st.session_state[f"flowops:suppress-canvas-selection:{book_id}"] = selected
    st.session_state.pop(f"flowops:canvas-selection:{book_id}", None)
    st.session_state.pop(f"flowops-canvas-{book_id}:hash", None)


def render_node_dialog(ui: Any, book: Runbook, node: Node, revision: int) -> None:
    import streamlit as st

    @st.dialog("Editar etapa", width="large", on_dismiss=lambda: dismiss_node(book.id))
    def editor() -> None:
        with st.container(key="flowops-node-editor"):
            content()

    def content() -> None:
        st.subheader(display(node.label) if node.label else node.action)
        st.caption(f"{node.id} · {node.action} · alterações no rascunho desta sessão")
        if node.action == "core.approval":
            st.info(
                "Esta etapa pausa uma execução efetiva em Aprovações. Na simulação do FlowOps, a aprovação é simulada e não cria uma pendência."
            )
        try:
            ui._node_tools(book, node, revision)
            with st.expander("Propriedades avançadas da etapa", expanded=False):
                ui._node_form(
                    book, node, revision, ui._granted("runbook.edit", book), include_config=False
                )
        except FlowOpsError as exc:
            render_error(exc)
        if st.button("Voltar ao fluxo", type="primary", key=f"flowops:close-node:{book.id}"):
            dismiss_node(book.id)
            st.rerun()

    editor()
