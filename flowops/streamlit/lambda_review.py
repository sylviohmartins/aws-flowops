"""Explicit read/review controls for Lambda changes in the node property panel."""

from flowops.domain.models import Node, Runbook
from flowops.persistence.repository import digest
from flowops.providers.aws.lambda_review import REVIEW_ACTIONS, review_lambda
from flowops.streamlit.ui import FlowOpsUI


def render_lambda_review(ui: FlowOpsUI, book: Runbook, node: Node, revision: int) -> None:
    if node.action not in REVIEW_ACTIONS:
        return
    import streamlit as st

    st.subheader("Revisão de alterações da Lambda")
    st.caption(
        "Revise a configuração, o pacote, o ambiente de execução, as versões, os aliases, as camadas e os metadados do artefato. Artefatos ZIP e contêineres não necessariamente possuem código-fonte editável nesta tela. Valores de variáveis de ambiente e URLs de download ficam ocultos."
    )
    key = f"flowops:lambda-review:{book.id}:{node.id}"
    fingerprint = digest(
        {"action": node.action, "config": node.config, "context": ui.aws.model_dump()}
    )
    if st.button(
        "Carregar estado ATUAL e comparar com o PROPOSTO",
        disabled=not ui._granted("aws.read", book),
        key=f"{key}:load",
    ):
        preview = review_lambda(ui.runtime.registry, ui.user, ui.aws, node.action, node.config)
        st.session_state[key] = {"fingerprint": fingerprint, "preview": preview}
    cached = st.session_state.get(key, {})
    if cached.get("fingerprint") != fingerprint:
        return
    preview = cached["preview"]
    for column, label, data in zip(
        st.columns(2),
        ("ATUAL", "PROPOSTO"),
        (preview["current"], preview["proposed"]),
        strict=True,
    ):
        column.markdown(f"**{label}**")
        column.json(data, expanded=False)
    st.code(preview["diff"] or "Nenhuma alteração.", language="diff")
    if preview["revision_id"] and st.button(
        "Aplicar RevisionId revisado",
        disabled=not ui._granted("runbook.edit", book),
        key=f"{key}:bind",
    ):
        node.config["RevisionId"] = preview["revision_id"]
        ui._store_working(book, revision)
        st.rerun()
