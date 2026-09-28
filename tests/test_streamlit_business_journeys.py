from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Edge, Identity, Node, Runbook, Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from tests.app_test_support import close_app_runtime


def element(elements: Any, label: str) -> Any:
    return next(item for item in elements if item.label == label)


def script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "standalone_app.py"


def test_runbook_management_and_resource_discovery_journey() -> None:
    with tempfile.TemporaryDirectory() as temp:
        previous = os.environ.get("FLOWOPS_DATABASE")
        database = Path(temp) / "management.db"
        os.environ["FLOWOPS_DATABASE"] = str(database)
        app = None
        try:
            app = AppTest.from_file(script_path()).run(timeout=20)
            app.sidebar.radio[0].set_value("Runbooks")
            app.run(timeout=20)
            element(app.text_input, "Nome do procedimento (opcional)").set_value("Managed Runbook")
            element(app.button, "Criar procedimento").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            assert len(Repository(database).list_runbooks()) == 1

            element(app.button, "Duplicar").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            assert len(Repository(database).list_runbooks()) == 2

            element(app.button, "Arquivar").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            repository = Repository(database)
            assert len(repository.list_runbooks()) == 1
            assert len(repository.list_runbooks(archived=True)) == 1

            element(app.button, "Excluir logicamente").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            assert Repository(database).list_runbooks() == []

            app.sidebar.radio[0].set_value("Resources")
            app.run(timeout=20)
            element(app.button, "Buscar recursos").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            assert any(
                "A busca de recursos é somente leitura" in caption.value for caption in app.caption
            )
        finally:
            if app is not None:
                close_app_runtime(app, Repository(database))
            if previous is None:
                os.environ.pop("FLOWOPS_DATABASE", None)
            else:
                os.environ["FLOWOPS_DATABASE"] = previous


def test_manual_approval_and_rerun_journey() -> None:
    with tempfile.TemporaryDirectory() as temp:
        previous = os.environ.get("FLOWOPS_DATABASE")
        database = Path(temp) / "approval.db"
        os.environ["FLOWOPS_DATABASE"] = str(database)
        runtime: FlowOpsRuntime | None = None
        app = None
        try:
            repository = Repository(database)
            book = Runbook(
                name="Approval Journey",
                nodes=[
                    Node(id="start", action="core.start"),
                    Node(
                        id="approval",
                        action="core.approval",
                        config={"message": "Review this execution"},
                    ),
                    Node(id="end", action="core.end"),
                ],
                edges=[
                    Edge(source="start", target="approval"),
                    Edge(source="approval", target="end"),
                ],
            )
            revision = repository.save_draft(book, "requester")
            published = repository.publish(book.id, "requester", revision)
            runtime = FlowOpsRuntime.demo(repository)
            execution = runtime.engine.submit(
                published,
                Identity(id="requester", roles=["ADMIN"]),
                AWSContext(),
                {},
                token="approval-journey",
                dry_run=False,
                reason="manual approval coverage",
            )
            waiting = runtime.engine.execute(execution.id)
            assert waiting.status == Status.WAITING_APPROVAL
            assert len(runtime.engine.store.pending_approvals()) == 1
            runtime.close()
            runtime = None

            app = AppTest.from_file(script_path()).run(timeout=20)
            app.sidebar.radio[0].set_value("Approvals")
            app.run(timeout=20)
            assert list(app.exception) == []
            element(app.text_input, "Motivo da decisão").set_value("reviewed and approved")
            element(app.button, "Aprovar").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            store = ExecutionStore(Repository(database))
            deadline = time.monotonic() + 3
            resumed = store.get(execution.id)
            while resumed.status not in {Status.SUCCESS, Status.FAILED, Status.CANCELLED}:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
                resumed = store.get(execution.id)
            assert resumed.status == Status.SUCCESS

            app.sidebar.radio[0].set_value("Executions")
            app.run(timeout=20)
            assert list(app.exception) == []
            element(app.button, "Executar novamente").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            deadline = time.monotonic() + 3
            history = store.history()
            while len(history) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
                history = store.history()
            assert len(history) == 2
            assert any(item.id != execution.id for item in history)

            app.sidebar.radio[0].set_value("Audit")
            app.run(timeout=20)
            element(app.text_input, "Filtrar evento").set_value("APPROV")
            app.run(timeout=20)
            assert list(app.exception) == []
            assert element(app.selectbox, "Detalhes do evento") is not None
        finally:
            if app is not None:
                close_app_runtime(app, repository)
            if runtime is not None:
                runtime.close()
            if previous is None:
                os.environ.pop("FLOWOPS_DATABASE", None)
            else:
                os.environ["FLOWOPS_DATABASE"] = previous
