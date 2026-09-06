"""Stable embedding boundary: the host owns identity, AWS context and authentication."""

from __future__ import annotations

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Identity
from flowops.persistence.repository import Repository, digest


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

        fingerprint = digest(
            {
                "repository": self.repository.database,
                "context": self.aws_context.model_dump(mode="json"),
                "generic_allowlist": sorted(self.generic_allowlist),
            }
        )[:20]
        key = f"flowops:runtime:{fingerprint}"
        runtime = st.session_state.get(key)
        if not isinstance(runtime, FlowOpsRuntime):
            runtime = (
                FlowOpsRuntime.demo(self.repository)
                if self.aws_context.mode == "demo"
                else FlowOpsRuntime.aws(
                    self.repository,
                    [self.aws_context],
                    generic_allowlist=self.generic_allowlist,
                )
            )
            st.session_state[key] = runtime
        return runtime

    def render(self) -> None:
        import streamlit as st

        from flowops.streamlit.workspace import FlowOpsWorkspaceUI

        st.title("AWS FlowOps Studio")
        st.caption("Visual, versioned and governed AWS operational runbooks")
        st.info(
            f"{self.aws_context.environment.upper()} · {self.aws_context.account_id} · "
            f"{self.aws_context.region} · {self.aws_context.mode.upper()}"
        )
        try:
            runtime = self._runtime()
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
            return
        FlowOpsWorkspaceUI(
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
