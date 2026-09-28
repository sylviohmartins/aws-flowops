"""Stable embedding boundary: the host owns identity, AWS context and authentication."""

from __future__ import annotations

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Identity
from flowops.persistence.repository import Repository, digest
from flowops.streamlit.component_locale import render_component_locale
from flowops.streamlit.layout import render_workspace_style
from flowops.streamlit.localization import display, render_error


def runtime_session_key(
    repository: Repository,
    aws_context: AWSContext | None = None,
    generic_allowlist: set[str] | None = None,
) -> str:
    """Return the stable Streamlit session key used for a FlowOps runtime."""
    context = aws_context or AWSContext()
    fingerprint = digest(
        {
            "repository": repository.database,
            "context": context.model_dump(mode="json"),
            "generic_allowlist": sorted(generic_allowlist or set()),
        }
    )[:20]
    return f"flowops:runtime:{fingerprint}"


class FlowOpsPage:
    """Embed FlowOps by supplying trusted identity/context, not persistence internals."""

    def __init__(
        self,
        user: Identity,
        aws_context: AWSContext,
        permissions: list[str] | None = None,
        *,
        repository: Repository | None = None,
        runtime: FlowOpsRuntime | None = None,
        generic_allowlist: set[str] | None = None,
        correlation_context: dict[str, str] | None = None,
    ):
        self.user = user.model_copy(deep=True)
        if permissions is not None:
            self.user.permissions = list(permissions)
        self.aws_context = aws_context.model_copy(deep=True)
        self.repository = repository or (
            runtime.repository if runtime else Repository.from_environment()
        )
        self.runtime = runtime
        self.generic_allowlist = set(generic_allowlist or set())
        self.correlation_context = dict(correlation_context or {})

    def _runtime(self) -> FlowOpsRuntime:
        if self.runtime is not None:
            return self.runtime
        import streamlit as st

        key = runtime_session_key(
            self.repository,
            self.aws_context,
            self.generic_allowlist,
        )
        runtime = st.session_state.get(key)
        if not isinstance(runtime, FlowOpsRuntime):
            if self.aws_context.mode == "demo":
                runtime = FlowOpsRuntime.demo(self.repository)
            elif self.aws_context.mode == "local":
                runtime = FlowOpsRuntime.local(self.repository, [self.aws_context])
            else:
                runtime = FlowOpsRuntime.aws(
                    self.repository,
                    [self.aws_context],
                    generic_allowlist=self.generic_allowlist,
                )
            st.session_state[key] = runtime
        return runtime

    def render(self) -> None:
        import streamlit as st

        render_workspace_style()
        with st.container(key="flowops-workspace"):
            self._render_workspace()

    def _render_workspace(self) -> None:
        import streamlit as st

        from flowops.streamlit.failure_workspace import FlowOpsGovernedUI

        render_component_locale()
        st.title("AWS FlowOps Studio")
        st.caption(
            "Procedimentos operacionais AWS visuais, versionados e com controles de segurança"
        )
        st.info(
            f"{display(self.aws_context.environment)} · {self.aws_context.account_id} · "
            f"{self.aws_context.region} · {display(self.aws_context.mode)}"
        )
        try:
            runtime = self._runtime()
        except (RuntimeError, ValueError) as exc:
            render_error(exc)
            return
        FlowOpsGovernedUI(
            self.user,
            self.aws_context,
            runtime,
            correlation_context=self.correlation_context,
        ).render()


def render_flowops(
    user: Identity,
    aws_context: AWSContext,
    *,
    permissions: list[str] | None = None,
    repository: Repository | None = None,
    runtime: FlowOpsRuntime | None = None,
    generic_allowlist: set[str] | None = None,
    correlation_context: dict[str, str] | None = None,
) -> None:
    FlowOpsPage(
        user,
        aws_context,
        permissions,
        repository=repository,
        runtime=runtime,
        generic_allowlist=generic_allowlist,
        correlation_context=correlation_context,
    ).render()
