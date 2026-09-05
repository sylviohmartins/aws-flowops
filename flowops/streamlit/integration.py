"""Stable embedding boundary: the host owns identity, AWS context and authentication."""

from __future__ import annotations

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Identity
from flowops.persistence.repository import Repository


class FlowOpsPage:
    def __init__(
        self,
        user: Identity,
        aws_context: AWSContext,
        permissions: list[str] | None = None,
        *,
        repository: Repository | None = None,
        runtime: FlowOpsRuntime | None = None,
    ):
        self.user = user.model_copy(deep=True)
        if permissions is not None:
            self.user.permissions = list(permissions)
        self.aws_context = aws_context.model_copy(deep=True)
        self.repository = repository or (runtime.repository if runtime else Repository())
        self.runtime = runtime

    def _runtime(self) -> FlowOpsRuntime:
        if self.runtime is not None:
            return self.runtime
        if self.aws_context.mode != "demo":
            raise RuntimeError(
                "Embedded AWS mode requires a host-supplied FlowOpsRuntime with trusted contexts."
            )
        import streamlit as st

        key = f"flowops:runtime:{self.repository.database}"
        runtime = st.session_state.get(key)
        if not isinstance(runtime, FlowOpsRuntime):
            runtime = FlowOpsRuntime.demo(self.repository)
            st.session_state[key] = runtime
        return runtime

    def render(self) -> None:
        import streamlit as st

        from flowops.streamlit.ui import FlowOpsUI

        st.title("AWS FlowOps Studio")
        st.caption("Visual, versioned and governed AWS operational runbooks")
        st.info(
            f"{self.aws_context.environment.upper()} · {self.aws_context.account_id} · "
            f"{self.aws_context.region} · {self.aws_context.mode.upper()}"
        )
        try:
            runtime = self._runtime()
        except RuntimeError as exc:
            st.error(str(exc))
            return
        FlowOpsUI(self.user, self.aws_context, runtime).render()


def render_flowops(
    user: Identity,
    aws_context: AWSContext,
    *,
    repository: Repository | None = None,
    runtime: FlowOpsRuntime | None = None,
) -> None:
    FlowOpsPage(user, aws_context, repository=repository, runtime=runtime).render()
