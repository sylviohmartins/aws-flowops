"""Application facade shared by standalone, embedded UI, tests and future API/CLI hosts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flowops.core.actions import ActionRegistry
from flowops.core.engine import Engine
from flowops.core.policies import PolicyEngine
from flowops.core.worker import LocalWorker
from flowops.domain.models import AWSContext
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import build_registry
from flowops.providers.aws.backend import BotoBackend
from flowops.providers.aws.catalog import ModelCatalog
from flowops.providers.aws.demo import DemoBackend


@dataclass
class FlowOpsRuntime:
    """Own execution services without making Streamlit part of their lifecycle."""

    repository: Repository
    registry: ActionRegistry
    engine: Engine
    worker: LocalWorker
    backend: Any

    @classmethod
    def demo(cls, repository: Repository) -> "FlowOpsRuntime":
        backend = DemoBackend(repository)
        registry = build_registry(backend)
        engine = Engine(repository, registry, policy=PolicyEngine(two_person=False))
        runtime = cls(repository, registry, engine, LocalWorker(engine), backend)
        runtime.worker.dispatch_pending()
        return runtime

    @classmethod
    def aws(
        cls,
        repository: Repository,
        contexts: list[AWSContext],
        *,
        policy: PolicyEngine | None = None,
    ) -> "FlowOpsRuntime":
        if not contexts or any(context.mode != "aws" for context in contexts):
            raise ValueError("Trusted AWS contexts are required for an AWS runtime.")
        backend = BotoBackend(contexts)
        registry = build_registry(backend, catalog=ModelCatalog())
        engine = Engine(repository, registry, policy=policy or PolicyEngine())
        runtime = cls(repository, registry, engine, LocalWorker(engine), backend)
        runtime.worker.dispatch_pending()
        return runtime

    @classmethod
    def from_registry(
        cls,
        repository: Repository,
        registry: ActionRegistry,
        *,
        policy: PolicyEngine | None = None,
        backend: Any = None,
    ) -> "FlowOpsRuntime":
        engine = Engine(repository, registry, policy=policy or PolicyEngine())
        runtime = cls(repository, registry, engine, LocalWorker(engine), backend)
        runtime.worker.dispatch_pending()
        return runtime

    def close(self) -> None:
        self.worker.close()
