import tempfile
import unittest
from pathlib import Path

from flowops.application import FlowOpsRuntime
from flowops.core.actions import ActionContext
from flowops.core.graph import validate_graph
from flowops.domain.models import AWSContext, Identity, Status
from flowops.persistence.repository import Repository
from flowops.templates import TEMPLATES, fix_stuck_payment


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = Repository(Path(self.temp.name) / "flowops.db")
        self.runtime = FlowOpsRuntime.demo(self.repository)
        self.addCleanup(self.runtime.close)
        self.admin = Identity(id="demo-admin", roles=["ADMIN"], teams=["payments"])

    def test_all_templates_have_valid_graphs(self) -> None:
        for template in TEMPLATES.values():
            with self.subTest(template=template.id):
                book = template.create(self.admin.id, "payments")
                order = validate_graph(book, self.runtime.registry)
                self.assertEqual(order[0], "start")
                self.assertIn("end", order)

    def test_fix_stuck_payment_dry_run_end_to_end(self) -> None:
        book = fix_stuck_payment(self.admin.id, "payments")
        revision = self.repository.save_draft(book, self.admin.id)
        published = self.repository.publish(book.id, self.admin.id, revision)
        execution = self.runtime.engine.submit(
            published,
            self.admin,
            AWSContext(environment="dev"),
            {"payment_id": "12345", "environment": "dev"},
            token="dry-run",
            dry_run=True,
            reason="demo",
        )
        result = self.runtime.engine.execute(execution.id)
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(result.node_outputs["validate_done"]["valid"], True)
        actual = self.runtime.registry.get("dynamodb.get_item").execute(
            {"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}},
            ActionContext("actual-check", "get", AWSContext(environment="dev"), False),
        )
        self.assertEqual(actual["Item"]["status"]["S"], "PROCESSING")

    def test_fix_stuck_payment_live_demo_pauses_and_resumes(self) -> None:
        book = fix_stuck_payment(self.admin.id, "payments")
        revision = self.repository.save_draft(book, self.admin.id)
        published = self.repository.publish(book.id, self.admin.id, revision)
        execution = self.runtime.engine.submit(
            published,
            self.admin,
            AWSContext(environment="dev"),
            {"payment_id": "12345", "environment": "dev"},
            token="live-demo",
            dry_run=False,
            reason="demo recovery",
        )
        paused = self.runtime.engine.execute(execution.id)
        self.assertEqual(paused.status, Status.WAITING_APPROVAL)
        approval = self.runtime.engine.store.pending_approvals()[0]
        self.runtime.engine.approve(
            paused.id,
            approval["node_id"],
            approval["digest"],
            self.admin,
            approved=True,
            reason="demo approval",
        )
        result = self.runtime.engine.execute(paused.id)
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(result.node_outputs["get_after"]["Item"]["status"]["S"], "PROCESSED")
