"""Keyboard-first graph editing and an ordered guide over the same Runbook."""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import Any

from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Edge, Runbook
from flowops.streamlit.localization import display, render_error


def ordered_nodes(book: Runbook) -> list[str]:
    incoming: dict[str, set[str]] = {node.id: set() for node in book.nodes}
    for edge in book.edges:
        if edge.target not in incoming or edge.source not in incoming:
            raise WorkflowValidationError("Uma conexão aponta para uma etapa inexistente.")
        incoming[edge.target].add(edge.source)
    try:
        return list(TopologicalSorter(incoming).static_order())
    except CycleError as exc:
        raise WorkflowValidationError(
            "Há um ciclo no fluxo. Revise as conexões antes de continuar."
        ) from exc


def branch_options(book: Runbook, source: str) -> list[str]:
    node = next(node for node in book.nodes if node.id == source)
    branches = ["true", "false"] if node.action == "core.condition" else ["default"]
    if node.action == "core.switch":
        branches += list(node.config.get("cases", {}))
    if node.failure_policy == "FAIL_BRANCH":
        branches.append("failure")
    return branches


def connect(book: Runbook, source: str, target: str, branch: str) -> Runbook:
    nodes = {node.id: node for node in book.nodes}
    if source not in nodes or target not in nodes or source == target:
        raise WorkflowValidationError("Escolha duas etapas existentes e diferentes.")
    if nodes[source].action in {"core.end", "core.stop"} or nodes[target].action == "core.start":
        raise WorkflowValidationError("Fim não tem saída e Início não recebe conexões.")
    edge = Edge(source=source, target=target, branch=branch)
    if branch not in branch_options(book, source) or edge in book.edges or len(book.edges) >= 1000:
        raise WorkflowValidationError(
            "Conexão duplicada, ramo inválido ou limite de conexões atingido."
        )
    edited = book.model_copy(deep=True)
    edited.edges.append(edge)
    ordered_nodes(edited)
    return edited


def render_connections(ui: Any, book: Runbook, revision: int) -> None:
    import streamlit as st

    if len(book.nodes) < 2:
        return
    editable = ui._granted("runbook.edit", book)
    key = f"flowops:connections:{book.id}"
    labels = {node.id: f"{display(node.label) or node.id} · {node.id}" for node in book.nodes}
    with st.expander("Conectar etapas sem arrastar", expanded=False):
        st.caption(
            "Escolha origem, destino e ramo. Isso altera apenas o rascunho da sessão; valide o fluxo completo antes de salvar. Ramos e junções existentes não são linearizados."
        )
        source = st.selectbox(
            "Etapa de origem",
            list(labels),
            format_func=lambda value: labels[value],
            key=key + ":source",
            disabled=not editable,
        )
        target = st.selectbox(
            "Etapa de destino",
            list(labels),
            format_func=lambda value: labels[value],
            key=key + ":target",
            disabled=not editable,
        )
        branch = st.selectbox(
            "Ramo da conexão",
            branch_options(book, source),
            format_func=display,
            key=key + ":branch",
            disabled=not editable,
        )
        if st.button("Adicionar conexão", key=key + ":add", disabled=not editable):
            try:
                require(ui.user, "runbook.edit", book)
                changed = connect(book, source, target, branch)
                ui._store_working(changed, revision)
                st.rerun()
            except FlowOpsError as exc:
                render_error(exc)
        if book.edges:
            selected = st.selectbox(
                "Conexão a remover",
                list(range(len(book.edges))),
                format_func=lambda index: (
                    f"{labels[book.edges[index].source]} → {labels[book.edges[index].target]} · {display(book.edges[index].branch)}"
                ),
                key=key + ":remove-index",
                disabled=not editable,
            )
            if st.button("Remover conexão", key=key + ":remove", disabled=not editable):
                require(ui.user, "runbook.edit", book)
                changed = book.model_copy(deep=True)
                changed.edges.pop(selected)
                ui._store_working(changed, revision)
                st.rerun()


GUIDANCE = {
    "dynamodb.query": "Escolha tabela e índice, defina a chave de partição e o limite. A consulta retorna uma lista em Items; use Mapear itens para preparar cada registro.",
    "dynamodb.get_item": "Informe a chave primária completa da tabela. GetItem não usa índice e retorna um único objeto em Item.",
    "core.filter": "Escolha uma lista, o campo de cada item, o operador e o valor. Somente os itens que satisfazem a comparação seguirão adiante.",
    "core.map": "Escolha a lista de entrada. No Modelo, crie os campos de saída e use a origem Item para selecionar os valores de cada registro; não é preciso escrever expressões.",
    "core.approval": "Explique o que o aprovador deve conferir. Na execução efetiva, o motor pausa e inclui os dados anteriores na solicitação; na simulação, não cria pendência.",
    "lambda.invoke": "Escolha a função e a modalidade de invocação. Monte o Payload como objeto/lista e conecte os resultados anteriores pela origem dos valores.",
}


def render_guided_step(ui: Any, book: Runbook, node_id: str, revision: int) -> None:
    import streamlit as st

    order = ordered_nodes(book)
    if any(
        sum(edge.source == current for edge in book.edges) > 1
        or sum(edge.target == current for edge in book.edges) > 1
        for current in order
    ):
        st.info(
            "Este fluxo possui ramos ou junções. A navegação abaixo acompanha dependências, não uma sequência de execução. Use a lista ou o canvas para revisar cada caminho; nenhuma conexão será removida."
        )
    node = next(node for node in book.nodes if node.id == node_id)
    index = order.index(node_id)
    st.caption(f"Etapa {index + 1} de {len(order)} · ordem de dependências, sem mudar o grafo")
    st.info(
        GUIDANCE.get(
            node.action,
            "Revise esta etapa e suas conexões. Aplique os campos antes de avançar; alterações ainda não aplicadas permanecem no editor da sessão.",
        )
    )
    ui._node_tools(book, node, revision)
    with st.expander("Propriedades avançadas da etapa", expanded=False):
        ui._node_form(book, node, revision, ui._granted("runbook.edit", book), include_config=False)
    for label, destination in (("Etapa anterior", index - 1), ("Próxima etapa", index + 1)):
        if st.button(
            label,
            key=f"flowops:guide:{book.id}:{label}",
            disabled=not 0 <= destination < len(order),
        ):
            st.session_state[f"flowops:pending-node:{book.id}"] = order[destination]
            st.rerun()
    st.caption(
        "Ao concluir: Validar → Salvar rascunho → Publicar versão. Depois abra Executar para preencher os parâmetros e iniciar a simulação. Nada é executado ao avançar no assistente."
    )
