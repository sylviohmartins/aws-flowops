"""Bounded session history. Durable revisions are never undone by this module."""

from dataclasses import dataclass, field
from typing import Any

from flowops.core.policies import require
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook
from flowops.streamlit.authoring import EditBuffer, pending_buffers


@dataclass
class EditHistory:
    revision: int
    past: list[str] = field(default_factory=list)
    future: list[str] = field(default_factory=list)

    def record(self, before: str, after: str) -> None:
        if before != after:
            self.past = (self.past + [before])[-40:]
            self.future.clear()

    def restore(self, current: str, revision: int, *, redo: bool = False) -> str:
        if revision != self.revision:
            raise WorkflowValidationError(
                "O histórico pertence a outra revisão. Recarregue o rascunho."
            )
        source, target = (self.future, self.past) if redo else (self.past, self.future)
        if not source:
            raise WorkflowValidationError("Não há alteração disponível para restaurar.")
        target.append(current)
        return source.pop()


def record_edit(session: Any, book: Runbook, revision: int, before: dict[str, Any] | None) -> None:
    key = f"flowops:history:{book.id}"
    history = session.get(key)
    if not isinstance(history, EditHistory) or history.revision != revision:
        session[key] = history = EditHistory(revision)
    if before and before["revision"] == revision:
        history.record(before["body"], book.model_dump_json())


def render_history(ui: Any, book: Runbook, revision: int) -> None:
    import streamlit as st

    history = st.session_state.get(f"flowops:history:{book.id}")
    if not isinstance(history, EditHistory) or history.revision != revision:
        return
    disabled = not ui._granted("runbook.edit", book) or bool(
        pending_buffers(book, st.session_state)
    )
    columns = st.columns(2)
    for column, label, redo, entries in (
        (columns[0], "Desfazer edição", False, history.past),
        (columns[1], "Refazer edição", True, history.future),
    ):
        if column.button(
            label,
            disabled=disabled or not entries,
            key=f"flowops:history:{book.id}:{redo}",
            help="Restaura uma alteração aplicada nesta sessão. Aplique ou descarte campos pendentes antes. Não altera versões publicadas.",
        ):
            require(ui.user, "runbook.edit", book)
            restored = history.restore(book.model_dump_json(), revision, redo=redo)
            st.session_state[ui._working_key(book)] = {"revision": revision, "body": restored}
            selection = f"flowops:node:{book.id}"
            if selection in st.session_state:
                st.session_state[f"flowops:pending-node:{book.id}"] = st.session_state[selection]
            # Never reuse epoch-zero widget IDs after restore: a late browser
            # event from the old form must not change the freshly restored data.
            restored_book = Runbook.model_validate_json(restored)
            configs = {
                f"flowops:visual:{book.id}:{node.id}:{node.action}": node.config
                for node in restored_book.nodes
            }
            configs[f"flowops:visual:{book.id}:parameters:core.parameters"] = {
                name: spec.model_dump(mode="json")
                for name, spec in restored_book.parameters.items()
            }
            replacements = {}
            for key, config in configs.items():
                previous = st.session_state.get(key)
                if isinstance(previous, EditBuffer):
                    replacement = EditBuffer.create(config)
                    replacement.epoch = previous.epoch + 1
                    replacement.mode = previous.mode
                    replacements[key] = replacement
            for session_key in list(st.session_state):
                if str(session_key).startswith(
                    (
                        f"flowops:visual:{book.id}:",
                        f"flowops-canvas-{book.id}:",
                        f"flowops:react:{book.id}:",
                    )
                ):
                    del st.session_state[session_key]
            st.session_state.update(replacements)
            st.session_state.pop(f"flowops:layout-undo:{book.id}", None)
            st.rerun()


def render_revision_conflict(ui: Any, book: Runbook, revision: int) -> bool:
    import streamlit as st

    cached = st.session_state.get(ui._working_key(book))
    if not isinstance(cached, dict) or cached["revision"] == revision:
        return False
    st.warning(
        "Outro editor salvou uma revisão mais recente. Seu rascunho e campos pendentes foram preservados; compare antes de recarregar."
    )
    with st.expander("Comparar rascunhos", expanded=True):
        st.caption(f"Sua revisão base: {cached['revision']} · revisão salva: {revision}")
        left, right = st.columns(2)
        left.json(cached["body"], expanded=False)
        right.json(book.model_dump(mode="json"), expanded=False)
    st.download_button(
        "Exportar meu rascunho preservado",
        cached["body"],
        file_name="rascunho-preservado.json",
        mime="application/json",
    )
    if st.button(
        "Carregar revisão salva e descartar minhas edições", key=f"flowops:conflict:{book.id}"
    ):
        st.session_state.pop(ui._working_key(book), None)
        for key in list(st.session_state):
            if str(key).startswith(f"flowops:visual:{book.id}:"):
                del st.session_state[key]
        st.rerun()
    return True
