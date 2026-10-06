from __future__ import annotations

from typing import Any

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext
from flowops.persistence.repository import Repository
from flowops.streamlit.integration import runtime_session_key


def runtime_from_app(
    app: Any,
    repository: Repository,
    aws_context: AWSContext | None = None,
) -> FlowOpsRuntime:
    key = runtime_session_key(repository, aws_context)
    runtime = app.session_state[key]
    assert isinstance(runtime, FlowOpsRuntime)
    return runtime


def close_app_runtime(
    app: Any,
    repository: Repository,
    aws_context: AWSContext | None = None,
) -> None:
    key = runtime_session_key(repository, aws_context)
    if key not in app.session_state:
        return
    runtime = app.session_state[key]
    if isinstance(runtime, FlowOpsRuntime):
        runtime.close()
