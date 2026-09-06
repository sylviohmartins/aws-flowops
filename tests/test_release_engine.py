"""Release regressions for impact bounds, reconciliation and durable completion."""

import time
import unittest
from typing import Any
from unittest.mock import patch

from flowops.core.actions import ActionRegistry, affected_records
from flowops.core.engine import Engine
from flowops.core.graph import validate_graph
from flowops.core.policies import PolicyEngine
from flowops.core.worker import LocalWorker
from flowops.domain.errors import PolicyViolation, ProviderError, WorkflowValidationError
from flowops.domain.models import Node, Status
from flowops.providers.aws.actions import AWSAction
from flowops.providers.aws.catalog import SPECS
from tests import test_engine as fixtures


class BatchAction(fixtures.FakeAction):
    def affected_records(self, config: dict[str, Any]) -> int:
        return len(config["records"])


class ReleaseEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.EngineTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_aws_batch_envelopes_and_s3_partial_failure(self) -> None:
        class Backend:
            def invoke(self, *args: Any) -> Any:
                return {"Errors": [{"Key": "one", "Code": "AccessDenied"}]}

        cases = [
            ("dynamodb.batch_get_item", {"RequestItems": {"payments": {"Keys": [{}, {}, {}]}}}),
            ("dynamodb.batch_write_item", {"RequestItems": {"payments": [{}, {}, {}]}}),
            ("dynamodb.transact_write_items", {"TransactItems": [{}, {}, {}]}),
            ("dynamodb.batch_execute_statement", {"Statements": [{}, {}, {}]}),
            ("dynamodb.execute_transaction", {"TransactStatements": [{}, {}, {}]}),
            ("sns.publish_batch", {"PublishBatchRequestEntries": [{}, {}, {}]}),
            ("sqs.delete_message_batch", {"Entries": [{}, {}, {}]}),
            ("s3.delete_objects", {"Delete": {"Objects": [{}, {}, {}]}}),
        ]
        for action_id, config in cases:
            with self.subTest(action=action_id):
                action = AWSAction(SPECS[action_id], Backend())
                self.assertEqual(affected_records(action, config), 3)
        action = AWSAction(SPECS["s3.delete_objects"], Backend())
        with self.assertRaises(ProviderError) as error:
            action.execute(
                cases[-1][1], fixtures.ActionContext("exec", "delete", fixtures.AWSContext(), False)
            )
        self.assertEqual(error.exception.code, "PartialFailure")
        self.assertIn("Errors", error.exception.details)
        self.assertEqual(affected_records(action, {}), 1)
        with self.assertRaises(WorkflowValidationError):
            affected_records(BatchAction(), {"records": []})

    def test_batch_and_iteration_limit_before_any_effect(self) -> None:
        f = self.fixture
        batch = BatchAction()
        registry = ActionRegistry()
        registry.register(batch)
        f.engine = Engine(f.repo, registry, policy=PolicyEngine(max_affected=3))
        each = Node(
            id="each",
            action="core.for_each",
            config={
                "items": [{"records": [1, 2]}, {"records": [3, 4]}],
                "template": "{{ item }}",
                "action": "test.action",
            },
        )
        for index, node in enumerate(
            [Node(id="call", action="test.action", config={"records": [1, 2, 3, 4]}), each]
        ):
            result = f.engine.execute(f.submit(f.book([node]), token=str(index)))
            self.assertEqual(result.status, Status.FAILED)
            self.assertIn("Affected-record limit", result.error)
            self.assertEqual(batch.calls, 0)

    def test_iteration_approval_covers_all_items_without_replay(self) -> None:
        f = self.fixture
        f.engine.policy = PolicyEngine(approval_threshold=1)
        node = Node(
            id="each",
            action="core.for_each",
            config={
                "items": [1, 2],
                "template": {"value": "{{ item }}"},
                "action": "test.action",
            },
        )
        execution_id = f.submit(f.book([node]))
        self.assertEqual(f.engine.execute(execution_id).status, Status.WAITING_APPROVAL)
        self.assertEqual(f.action.calls, 0)
        approval = f.engine.store.pending_approvals()[0]
        self.assertEqual(approval["body"]["preview"]["affected"], 2)
        f.engine.approve(
            execution_id,
            "each",
            approval["digest"],
            f.other,
            approved=True,
            reason="Review both items",
        )
        self.assertEqual(f.engine.execute(execution_id).status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 2)
        f.engine.execute(execution_id)
        self.assertEqual(f.action.calls, 2)

    def test_manual_intervention_records_reconciliation_without_replaying_call(self) -> None:
        f = self.fixture
        f.action.failures = 1
        execution_id = f.submit(
            f.book([Node(id="call", action="test.action", failure_policy="MANUAL_INTERVENTION")])
        )
        self.assertEqual(f.engine.execute(execution_id).status, Status.WAITING_APPROVAL)
        approval = f.engine.store.pending_approvals()[0]
        with self.assertRaises(PolicyViolation):
            f.engine.approve(
                execution_id, "call", approval["digest"], f.actor, approved=True, reason="self"
            )
        f.engine.approve(
            execution_id,
            "call",
            approval["digest"],
            f.other,
            approved=True,
            reason="Reconciled externally, ticket OPS-9",
        )
        result = f.engine.execute(execution_id)
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(
            result.node_outputs["call"], {"manual_intervention": True, "reconciled": True}
        )
        self.assertEqual(f.action.calls, 1)
        self.assertEqual(f.engine.store.nodes(execution_id)["call"]["error"], "ThrottlingException")
        self.assertEqual(f.engine.store.pending_approvals(), [])

    def test_success_checkpoint_contains_result_at_first_terminal_write(self) -> None:
        f = self.fixture
        execution_id = f.submit(f.book())
        checkpoint = f.engine.store.checkpoint

        def crash_after_success(
            execution: Any, node_id: str, status: Status, detail: dict[str, Any]
        ) -> None:
            checkpoint(execution, node_id, status, detail)
            if node_id == "call" and status == Status.SUCCESS:
                raise KeyboardInterrupt("process death after commit")

        with (
            patch.object(f.engine.store, "checkpoint", side_effect=crash_after_success),
            self.assertRaises(KeyboardInterrupt),
        ):
            f.engine.execute(execution_id)
        self.assertEqual(f.engine.store.nodes(execution_id)["call"]["output"]["result"], "ok")
        recovered = f.engine.store.get(execution_id)
        recovered.status = Status.PENDING
        f.engine.store.save(recovered)
        self.assertEqual(f.engine.execute(execution_id).status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 1)

    def test_iteration_checkpoint_collisions_fail_validation(self) -> None:
        f = self.fixture
        for ids in (("each", "each__0"), ("a" * 49, "a" * 48 + "b")):
            book = f.book(
                [
                    Node(id=value, action="core.for_each", config={"items": [], "template": {}})
                    for value in ids
                ]
            )
            with self.assertRaisesRegex(WorkflowValidationError, "checkpoint IDs"):
                validate_graph(book, f.registry)

    def test_dispatcher_retries_a_durable_pending_execution_after_lock_release(self) -> None:
        f = self.fixture
        book = f.book()
        first, second = f.submit(book), f.submit(book, token="two")
        self.assertTrue(f.engine.store.claim(first))
        worker = LocalWorker(f.engine)
        self.addCleanup(worker.close)
        worker.start()
        worker.start()
        self.assertEqual(worker.enqueue(second).result(timeout=2).status, Status.PENDING)
        first_run = f.engine.store.get(first)
        first_run.status = Status.CANCELLED
        f.engine.store.save(first_run)
        deadline = time.monotonic() + 3
        while f.engine.store.get(second).status != Status.SUCCESS and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(f.engine.store.get(second).status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 1)

    def test_dispatcher_recovers_after_storage_error(self) -> None:
        f = self.fixture
        worker = LocalWorker(f.engine)
        self.addCleanup(worker.close)
        with patch.object(worker, "dispatch_pending", side_effect=[RuntimeError("private DSN"), None]) as dispatch:
            with patch.object(worker.stopping, "wait", side_effect=[False, False, True]):
                with self.assertLogs("flowops.worker", level="WARNING") as logs:
                    worker._dispatch_loop()
            self.assertEqual(dispatch.call_count, 2)
            self.assertNotIn("private DSN", str(logs.output))

    def test_compound_action_iam_metadata_uses_real_permissions(self) -> None:
        class Backend:
            def invoke(self, *args: Any) -> Any:
                return {}

        expected = {
            "sns.publish_batch": ("sns:Publish",),
            "dynamodb.transact_get_items": ("dynamodb:GetItem",),
            "dynamodb.transact_write_items": ("dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"),
        }
        for key, permissions in expected.items():
            self.assertEqual(AWSAction(SPECS[key], Backend()).metadata.required_permissions, permissions)

    def test_iteration_rate_limit_is_bounded_and_preserves_simulation(self) -> None:
        f = self.fixture
        node = Node(id="each", action="core.for_each", config={
            "items": [1, 2], "template": {"value": "{{ item }}"},
            "action": "test.action", "interval_seconds": 0.01,
        })
        self.assertEqual(f.engine.execute(f.submit(f.book([node]))).status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 2)

        node.config["interval_seconds"] = 11
        result = f.engine.execute(f.submit(f.book([node]), token="bad-interval"))
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("Iteration interval", result.error)
        self.assertEqual(f.action.calls, 2)
        node.config["interval_seconds"] = 10
        with patch("flowops.core.engine.time.sleep", side_effect=AssertionError("Simulation cannot wait")):
            result = f.engine.execute(f.submit(f.book([node]), token="simulation-interval", dry_run=True))
        self.assertEqual(result.status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 2)

    def test_failed_iteration_can_be_reconciled_without_repeating_partial_work(self) -> None:
        f = self.fixture
        f.action.failures = 1
        node = Node(id="each", action="core.for_each", failure_policy="MANUAL_INTERVENTION", config={
            "items": [1, 2], "template": {"value": "{{ item }}"}, "action": "test.action",
        })
        execution_id = f.submit(f.book([node]))
        self.assertEqual(f.engine.execute(execution_id).status, Status.WAITING_APPROVAL)
        self.assertEqual(f.engine.store.nodes(execution_id)["each__0"]["status"], Status.FAILED)
        approval = f.engine.store.pending_approvals()[0]
        f.engine.approve(execution_id, "each", approval["digest"], f.other, approved=True, reason="Whole batch reconciled externally")
        self.assertEqual(f.engine.execute(execution_id).status, Status.SUCCESS)
        self.assertEqual(f.action.calls, 1)


if __name__ == "__main__":
    unittest.main()
