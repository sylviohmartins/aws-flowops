"""Actionable presentation diagnostics over the existing authoritative validators."""

from dataclasses import dataclass
from typing import Any

from flowops.core.graph import LOGIC_REQUIRED, validate_graph
from flowops.domain.errors import FlowOpsError
from flowops.domain.models import Runbook
from flowops.streamlit.authoring import pending_buffers
from flowops.streamlit.localization import error_text, field_label


@dataclass(frozen=True)
class ReviewIssue:
    node_id: str
    field: str
    message: str


def review_issues(book: Runbook, registry: Any) -> list[ReviewIssue]:
    from flowops.streamlit.value_editor import _validate_references

    issues = []
    for node in book.nodes:
        try:
            required = (
                LOGIC_REQUIRED[node.action]
                if node.action in LOGIC_REQUIRED
                else registry.get(node.action).metadata.input_schema.get("required", [])
            )
            for name in required:
                value = node.config.get(name)
                if name not in node.config or value is None or value == "":
                    issues.append(ReviewIssue(node.id, name, "Preencha o campo obrigatório."))
            _validate_references(book, node, node.config, registry)
        except (FlowOpsError, ValueError) as exc:
            issues.append(ReviewIssue(node.id, "config", str(exc)))
    try:
        validate_graph(book, registry)
    except (FlowOpsError, ValueError) as exc:
        issues.append(ReviewIssue("", "fluxo", str(exc)))
    return issues


def render_review(ui: Any, book: Runbook, revision: int) -> None:
    import streamlit as st

    with st.expander("Revisar pendências e próximos passos", expanded=False):
        pending = pending_buffers(book, st.session_state)
        issues = review_issues(book, ui.runtime.registry)
        labels = {node.id: node.label or node.id for node in book.nodes}
        for node_id in pending:
            st.warning(f"{labels.get(node_id, node_id)}: há campos ainda não aplicados.")
        for issue in issues:
            st.warning(
                f"{labels.get(issue.node_id, 'Conexões do fluxo')} · {field_label(issue.field)}: {error_text(issue.message)}"
            )
        targets = list(
            dict.fromkeys(
                [item for item in pending if item in labels]
                + [issue.node_id for issue in issues if issue.node_id in labels]
            )
        )
        for target in targets:
            if st.button(f"Corrigir {labels[target]}", key=f"flowops:review:{book.id}:{target}"):
                st.session_state[f"flowops:pending-node:{book.id}"] = target
                st.session_state[f"flowops:node-dialog:{book.id}"] = target
                st.rerun()
        if not issues and not pending:
            st.success(
                "Revisão estrutural sem pendências. Confira os recursos, dados e riscos antes de publicar."
            )
        st.caption(
            f"Revisão salva {revision}. Aplicar altera a sessão; Salvar registra um rascunho; Publicar cria uma versão imutável."
        )
        if st.button("Abrir execução de versão publicada", key=f"flowops:review:{book.id}:execute"):
            st.session_state["flowops:next-page"] = "Execute"
            st.rerun()
