import tempfile
import unittest
from pathlib import Path
from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.core.engine import Engine
from flowops.domain.models import AWSContext, Edge, Identity, Node, Risk, Runbook, Status
from flowops.persistence.repository import Repository


class WriteAction:
    metadata = Metadata(
        "test.write",
        "test",
        "test",
        "write",
        "Mutation",
        risk=Risk.HIGH,
        read_only=False,
        idempotent=False,
    )

    def validate(self, config: dict[str, Any]) -> None:
        return None

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        return {"simulation": True}

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        return {"ok": True}


class ApprovalAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "test.db")
        registry = ActionRegistry()
        registry.register(WriteAction())
        self.engine = Engine(self.repo, registry)
        self.requester = Identity(id="requester", roles=["ADMIN"], teams=["payments"])
        self.approver = Identity(id="approver", roles=["APPROVER"], teams=["payments"])

    def published(self) -> Runbook:
        book = Runbook(
            name="Production repair",
            team="payments",
            environments=["production"],
            nodes=[
                Node(id="start", action="core.start"),
                Node(id="write", action="test.write", config={"record": "123"}),
                Node(id="end", action="core.end"),
            ],
            edges=[Edge(source="start", target="write"), Edge(source="write", target="end")],
        )
        revision = self.repo.save_draft(book, self.requester.id)
        return self.repo.publish(book.id, self.requester.id, revision)

    def test_approval_preview_is_durable_contextual_and_auditable(self) -> None:
        book = self.published()
        execution = self.engine.submit(
            book,
            self.requester,
            AWSContext(
                environment="production",
                account_id="123456789012",
                region="sa-east-1",
            ),
            {},
            token="prod-1",
            dry_run=False,
            reason="INC-2026-001",
        )
        paused = self.engine.execute(execution.id)
        self.assertEqual(paused.status, Status.WAITING_APPROVAL)

        approval = self.engine.store.pending_approvals()[0]
        body = approval["body"]
        self.assertEqual(body["environment"], "production")
        self.assertEqual(body["account"], "123456789012")
        self.assertEqual(body["region"], "sa-east-1")
        self.assertEqual(body["reason"], "INC-2026-001")
        self.assertEqual(body["preview"]["action"], "test.write")
        self.assertEqual(body["preview"]["affected"], 1)
        self.assertEqual(body["preview"]["risk"], "HIGH")

        requested = next(
            event
            for event in self.repo.events(execution.id)
            if event["event"] == "APPROVAL_REQUESTED"
        )
        self.assertEqual(requested["body"]["environment"], "production")
        self.assertEqual(requested["body"]["reason"], "INC-2026-001")

        self.engine.approve(
            execution.id,
            "write",
            approval["digest"],
            self.approver,
            approved=True,
            reason="peer reviewed",
        )
        completed = self.engine.execute(execution.id)
        self.assertEqual(completed.status, Status.SUCCESS)

        events = self.repo.events(execution.id)
        approval_event = next(event for event in events if event["event"] == "EXECUTION_APPROVED")
        self.assertEqual(approval_event["body"]["result"], "APPROVED")
        self.assertEqual(approval_event["body"]["approval_reason"], "peer reviewed")
        completion = next(event for event in events if event["event"] == "EXECUTION_COMPLETED")
        self.assertEqual(completion["body"]["result"], "SUCCESS")
        self.assertEqual(completion["body"]["environment"], "production")


if __name__ == "__main__":
    unittest.main()
