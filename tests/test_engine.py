import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.engine import Engine
from flowops.core.logic import logic
from flowops.core.security import bounded_output, redact
from flowops.core.worker import LocalWorker
from flowops.domain.errors import ConflictError, PolicyViolation, ProviderError
from flowops.domain.models import AWSContext, Edge, Identity, Node, RetryPolicy, Risk, Runbook, Status
from flowops.persistence.repository import Repository


class FakeAction:
    def __init__(self, *, read_only: bool = False, idempotent: bool = False):
        self.metadata = Metadata("test.action", "test", "test", "action", "Explicit test fake", risk=Risk.HIGH, read_only=read_only, idempotent=idempotent)
        self.calls = 0
        self.failures = 0

    def validate(self, config: dict[str, Any]) -> None:
        pass

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return {"simulation": True, "native_dry_run": False}

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise ProviderError("ThrottlingException", retryable=True)
        return {"result": "ok", "SecretAccessKey": "never-persist"}


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "test.db")
        self.registry = ActionRegistry()
        self.action = FakeAction()
        self.registry.register(self.action)
        self.engine = Engine(self.repo, self.registry)
        self.actor = Identity(id="requester", roles=["ADMIN"])
        self.other = Identity(id="approver", roles=["APPROVER"])

    def book(self, middle: list[Node] | None = None, *, production: bool = False) -> Runbook:
        nodes = [Node(id="start", action="core.start"), *(middle if middle is not None else [Node(id="call", action="test.action")]), Node(id="end", action="core.end")]
        book = Runbook(name="Test", nodes=nodes, edges=[Edge(source=a.id, target=b.id) for a, b in zip(nodes, nodes[1:])], environments=["dev", "production"] if production else ["dev"])
        rev = self.repo.save_draft(book, self.actor.id)
        return self.repo.publish(book.id, self.actor.id, rev)

    def submit(self, book: Runbook, *, token: str = "one", dry_run: bool = False, production: bool = False) -> str:
        return self.engine.submit(book, self.actor, AWSContext(environment="production" if production else "dev"), {}, token=token, dry_run=dry_run, reason="test recovery").id

    def test_duplicate_submit_and_worker_claim(self) -> None:
        book = self.book()
        first = self.submit(book)
        self.assertEqual(first, self.submit(book))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.engine.execute, [first, first]))
        self.assertEqual(self.action.calls, 1)
        self.assertEqual(self.engine.store.get(first).status, Status.SUCCESS)
        self.engine.execute(first)
        self.assertEqual(self.action.calls, 1)
        self.assertNotIn("never-persist", Path(self.repo.database).read_bytes().decode(errors="ignore"))
        with self.assertRaises(ConflictError):
            self.submit(book, dry_run=True)

    def test_simulation_never_calls_mutation(self) -> None:
        result = self.engine.execute(self.submit(self.book(), dry_run=True))
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(self.action.calls, 0)
        self.assertTrue(result.node_outputs["call"]["simulation"])

    def test_production_approval_two_person_and_resume(self) -> None:
        execution_id = self.submit(self.book(production=True), production=True)
        self.assertEqual(self.engine.execute(execution_id).status, Status.WAITING_APPROVAL)
        approval = self.engine.store.pending_approvals()[0]
        with self.assertRaises(PolicyViolation):
            self.engine.approve(execution_id, "call", approval["digest"], self.actor, approved=True, reason="self")
        self.engine.approve(execution_id, "call", approval["digest"], self.other, approved=True, reason="Reviewed")
        self.assertEqual(self.engine.execute(execution_id).status, Status.SUCCESS)
        self.assertEqual(self.action.calls, 1)
        with self.assertRaises(ConflictError):
            self.engine.approve(execution_id, "call", approval["digest"], self.other, approved=True, reason="replay")

    def test_manual_checkpoint_and_cancellation(self) -> None:
        book = self.book([Node(id="approval", action="core.approval"), Node(id="call", action="test.action")])
        execution_id = self.submit(book)
        self.assertEqual(self.engine.execute(execution_id).status, Status.WAITING_APPROVAL)
        self.engine.cancel(execution_id, self.actor)
        self.assertEqual(self.engine.execute(execution_id).status, Status.CANCELLED)
        self.assertEqual(self.action.calls, 0)

    def test_retries_only_when_safe(self) -> None:
        retry = RetryPolicy(max_attempts=2, backoff_seconds=0)
        book = self.book([Node(id="call", action="test.action", retry=retry)])
        self.assertEqual(self.engine.execute(self.submit(book)).status, Status.FAILED)
        self.assertEqual(self.action.calls, 0)
        registry = ActionRegistry()
        safe = FakeAction(read_only=True, idempotent=True)
        safe.failures = 1
        registry.register(safe)
        engine = Engine(self.repo, registry)
        execution_id = self.submit(book, token="safe")
        self.assertEqual(engine.execute(execution_id).status, Status.SUCCESS)
        self.assertEqual(safe.calls, 2)

    def test_condition_skips_unselected_branch(self) -> None:
        book = Runbook(name="Branches", environments=["dev"], nodes=[Node(id="start", action="core.start"), Node(id="condition", action="core.condition", config={"left": False, "right": True}), Node(id="call", action="test.action"), Node(id="end", action="core.end")], edges=[Edge(source="start", target="condition"), Edge(source="condition", target="call", branch="true"), Edge(source="condition", target="end", branch="false"), Edge(source="call", target="end")])
        rev = self.repo.save_draft(book, "author")
        result = self.engine.execute(self.submit(self.repo.publish(book.id, "author", rev)))
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(self.engine.store.nodes(result.id)["call"]["status"], Status.SKIPPED)
        self.assertEqual(self.action.calls, 0)

    def test_local_worker_executes_off_ui_thread(self) -> None:
        worker = LocalWorker(self.engine)
        self.addCleanup(worker.close)
        future = worker.enqueue(self.submit(self.book()))
        self.assertEqual(future.result(timeout=5).status, Status.SUCCESS)

    def test_bounded_logic_and_redaction(self) -> None:
        result, _ = logic("core.map", {"items": [{"id": 1}], "template": {"Key": "{{ item.id }}"}}, {})
        self.assertEqual(result, {"items": [{"Key": 1}]})
        self.assertEqual(logic("core.batch", {"items": [1, 2, 3], "size": 2}, {})[0], {"batches": [[1, 2], [3]]})
        self.assertTrue(bounded_output({"big": "x" * 1000}, 50)["_truncated"])
        self.assertEqual(redact({"MessageBody": '{"password":"secret"}'}), {"MessageBody": '{"password": "[REDACTED]"}'})
