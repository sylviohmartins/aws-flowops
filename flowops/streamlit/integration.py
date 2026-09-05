"""Embedding boundary: the host owns identity, AWS context and application bootstrap."""

from flowops.domain.models import AWSContext, Identity, Runbook
from flowops.persistence.repository import Repository


class FlowOpsPage:
    def __init__(
        self,
        user: Identity,
        aws_context: AWSContext,
        permissions: list[str] | None = None,
        *,
        repository: Repository | None = None,
    ):
        self.user = user.model_copy(deep=True)
        if permissions is not None:
            self.user.permissions = list(permissions)
        self.aws_context = aws_context
        self.repository = repository or Repository()

    def render(self) -> None:
        import streamlit as st

        st.title("AWS FlowOps Studio")
        st.caption("Runbooks operacionais • Python + Streamlit")
        st.info(
            f"{self.aws_context.environment.upper()} · {self.aws_context.account_id} · {self.aws_context.region}"
        )
        with st.form("create_runbook"):
            name = st.text_input("Nome do runbook")
            description = st.text_area("Descrição")
            if st.form_submit_button("Criar runbook") and name.strip():
                book = Runbook(name=name.strip(), description=description, owner=self.user.id)
                self.repository.save_draft(book, self.user.id)
                st.success("Runbook salvo.")
        for book in self.repository.list_runbooks():
            st.write(f"**{book.name}** — {book.description}")


def render_flowops(
    user: Identity, aws_context: AWSContext, *, repository: Repository | None = None
) -> None:
    FlowOpsPage(user, aws_context, repository=repository).render()
