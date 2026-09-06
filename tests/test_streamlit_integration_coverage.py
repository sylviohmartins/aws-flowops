from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import flowops.streamlit.failure_workspace as failure_workspace
import flowops.streamlit.integration as integration
from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Identity
from flowops.persistence.repository import Repository
from flowops.streamlit.integration import FlowOpsPage


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.messages: list[tuple[str, str]] = []

    def title(self, value: str) -> None:
        self.messages.append(("title", value))

    def caption(self, value: str) -> None:
        self.messages.append(("caption", value))

    def info(self, value: str) -> None:
        self.messages.append(("info", value))

    def error(self, value: str) -> None:
        self.messages.append(("error", value))


def test_page_copies_host_context_permissions_and_uses_supplied_runtime(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "embedded.db")
    runtime = FlowOpsRuntime.demo(repo)
    user = Identity(id="host-user", permissions=["original"])
    context = AWSContext()
    page = FlowOpsPage(
        user,
        context,
        permissions=["runbook.read"],
        runtime=runtime,
        generic_allowlist={"ec2.describe_instances"},
        correlation_context={"ticket": "OPS-1"},
    )

    assert page.user is not user
    assert page.aws_context is not context
    assert page.user.permissions == ["runbook.read"]
    assert user.permissions == ["original"]
    assert page.repository is repo
    assert page.generic_allowlist == {"ec2.describe_instances"}
    assert page.correlation_context == {"ticket": "OPS-1"}
    assert page._runtime() is runtime


def test_page_builds_and_caches_demo_and_aws_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_streamlit = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    repo = Repository(tmp_path / "runtime.db")
    user = Identity(id="host-user")

    demo_page = FlowOpsPage(user, AWSContext(), repository=repo)
    first = demo_page._runtime()
    assert first is demo_page._runtime()
    assert len(fake_streamlit.session_state) == 1

    calls: list[tuple[list[AWSContext], set[str]]] = []

    def fake_aws(
        repository: Repository,
        contexts: list[AWSContext],
        *,
        generic_allowlist: set[str] | None = None,
    ) -> FlowOpsRuntime:
        calls.append((contexts, set(generic_allowlist or set())))
        return FlowOpsRuntime.demo(repository)

    monkeypatch.setattr(FlowOpsRuntime, "aws", fake_aws)
    aws_context = AWSContext(mode="aws", account_id="123456789012")
    aws_page = FlowOpsPage(
        user,
        aws_context,
        repository=repo,
        generic_allowlist={"ec2.describe_instances"},
    )
    created = aws_page._runtime()
    assert isinstance(created, FlowOpsRuntime)
    assert calls[0][0][0] == aws_context
    assert calls[0][1] == {"ec2.describe_instances"}
    assert aws_page._runtime() is created
    assert len(fake_streamlit.session_state) == 2


def test_page_render_success_and_runtime_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_streamlit = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    repo = Repository(tmp_path / "render.db")
    runtime = FlowOpsRuntime.demo(repo)
    rendered: list[tuple[str, AWSContext, dict[str, str]]] = []

    class FakeUI:
        def __init__(
            self,
            user: Identity,
            context: AWSContext,
            supplied_runtime: FlowOpsRuntime,
            *,
            correlation_context: dict[str, str],
        ) -> None:
            assert supplied_runtime is runtime
            rendered.append((user.id, context, correlation_context))

        def render(self) -> None:
            rendered.append(("rendered", AWSContext(), {}))

    monkeypatch.setattr(failure_workspace, "FlowOpsGovernedUI", FakeUI)
    page = FlowOpsPage(
        Identity(id="operator"),
        AWSContext(),
        runtime=runtime,
        correlation_context={"ticket": "OPS-2"},
    )
    page.render()
    assert ("title", "AWS FlowOps Studio") in fake_streamlit.messages
    assert rendered[0][0] == "operator"
    assert rendered[0][2] == {"ticket": "OPS-2"}
    assert rendered[-1][0] == "rendered"

    def invalid_runtime() -> FlowOpsRuntime:
        raise ValueError("invalid runtime configuration")

    page._runtime = invalid_runtime  # type: ignore[method-assign]
    page.render()
    assert ("error", "invalid runtime configuration") in fake_streamlit.messages


def test_render_flowops_wrapper_forwards_host_owned_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakePage:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

        def render(self) -> None:
            captured["rendered"] = True

    monkeypatch.setattr(integration, "FlowOpsPage", FakePage)
    user = Identity(id="host")
    context = AWSContext()
    integration.render_flowops(
        user,
        context,
        permissions=["runbook.read"],
        generic_allowlist={"ec2.describe_instances"},
        correlation_context={"ticket": "OPS-3"},
    )
    assert captured["args"] == (user, context, ["runbook.read"])
    assert captured["kwargs"]["generic_allowlist"] == {"ec2.describe_instances"}
    assert captured["kwargs"]["correlation_context"] == {"ticket": "OPS-3"}
    assert captured["rendered"] is True
