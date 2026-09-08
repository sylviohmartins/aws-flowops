"""Lab transport boundaries and real business outcomes in the Docker emulator."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from flowops.application import FlowOpsRuntime
from flowops.core.actions import ActionContext
from flowops.core.engine import Engine
from flowops.core.policies import PolicyEngine
from flowops.domain.errors import PolicyViolation
from flowops.domain.models import AWSContext, Identity, Status, new_id
from flowops.lab_templates import lab_runbooks
from flowops.persistence.repository import Repository
from flowops.providers.aws import lab, local
from flowops.providers.aws.actions import build_registry
from flowops.providers.aws.backend import resource_scope
from flowops.providers.aws.catalog import ModelCatalog
from flowops.providers.aws.lab_lambda import handler


class LocalBoundaryTests(unittest.TestCase):
    def test_endpoint_and_context_cannot_escape_lab(self) -> None:
        for endpoint in (
            "https://127.0.0.1:5000",
            "http://localhost:5000",
            "http://169.254.169.254:80",
            "http://127.0.0.1",
            "http://127.0.0.1:5000/path",
            "http://user@127.0.0.1:5000",
            "http://127.0.0.1:5000?q=1",
            "http://127.0.0.1:99999",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(PolicyViolation):
                local.validate_local_endpoint(endpoint)
        self.assertEqual(
            local.validate_local_endpoint(local.LOCAL_ENDPOINT + "/"), local.LOCAL_ENDPOINT
        )
        for changes in (
            {"mode": "aws"},
            {"environment": "production"},
            {"account_id": "999999999999"},
            {"profile": "real"},
            {"role_arn": "real"},
            {"external_id": "real"},
        ):
            with self.subTest(changes=changes), self.assertRaises(PolicyViolation):
                local.LocalAWSBackend([local.local_context().model_copy(update=changes)])
        with self.assertRaises(PolicyViolation):
            local.LocalAWSBackend([])
        backend = local.LocalAWSBackend([local.local_context()])
        with self.assertRaises(PolicyViolation):
            backend._client("sqs", ActionContext("bad", "read", AWSContext(), True))
        queue = local.LOCAL_ENDPOINT + "/123456789012/test"
        resource_scope(
            {"nested": [{"QueueUrl": queue}]},
            local.local_context(),
            queue_endpoint=local.LOCAL_ENDPOINT,
        )
        for value in (
            "https://sqs.sa-east-1.amazonaws.com/123456789012/test",
            local.LOCAL_ENDPOINT + "/999999999999/test",
            local.LOCAL_ENDPOINT + "/123456789012/../other",
            local.LOCAL_ENDPOINT + "/123456789012/%2e%2e/other",
        ):
            with self.assertRaises(PolicyViolation):
                resource_scope(
                    {"QueueUrl": value}, local.local_context(), queue_endpoint=local.LOCAL_ENDPOINT
                )
        with self.assertRaises(PolicyViolation):
            resource_scope(
                {"QueueUrl": queue}, AWSContext(mode="aws"), queue_endpoint=local.LOCAL_ENDPOINT
            )

    def test_ambient_credentials_profiles_endpoints_and_proxy_are_ignored(self) -> None:
        env = {
            "AWS_PROFILE": "must-not-exist",
            "AWS_CONFIG_FILE": "/does/not/exist",
            "AWS_SHARED_CREDENTIALS_FILE": "/does/not/exist",
            "AWS_ACCESS_KEY_ID": "REAL-MUST-NOT-USE",
            "AWS_SECRET_ACCESS_KEY": "REAL-MUST-NOT-USE",
            "AWS_ENDPOINT_URL": "https://example.invalid",
            "AWS_ENDPOINT_URL_DYNAMODB": "https://example.invalid",
            "HTTPS_PROXY": "http://example.invalid:80",
        }
        with patch.dict(os.environ, env):
            session = local.local_session()
            self.assertEqual(session.get_credentials().access_key, "testing")
            client = local.local_client("dynamodb")
            self.addCleanup(client.close)
            self.assertEqual(client.meta.endpoint_url, local.LOCAL_ENDPOINT)
            self.assertEqual(client.meta.config.proxies, {})
            # Botocore consumes the endpoint flag while building the client. Assert its
            # observable endpoint above, rather than an internal normalized Config value.
            self.assertEqual(os.environ["AWS_PROFILE"], "must-not-exist")

    def test_account_verification_cache_release_and_mismatch(self) -> None:
        backend = local.LocalAWSBackend([local.local_context()])
        context = ActionContext("local", "read", local.local_context(), True)
        sts, client = MagicMock(), MagicMock()
        sts.get_caller_identity.return_value = {"Account": local.LOCAL_ACCOUNT}
        with patch.object(local, "local_client", side_effect=[sts, client]) as factory:
            self.assertIs(backend._client("sqs", context), client)
            self.assertIs(backend._client("sqs", context), client)
            self.assertEqual(factory.call_count, 2)
        sts.close.assert_called_once()
        backend.release("local")
        client.close.assert_called_once()
        sts.get_caller_identity.return_value = {"Account": "999999999999"}
        with (
            patch.object(local, "local_client", return_value=sts),
            self.assertRaises(PolicyViolation),
        ):
            backend._client("sqs", context)
        self.assertFalse(backend.sessions)

    def test_templates_are_published_once_and_operator_edits_survive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "lab.db")
            self.assertEqual(len(lab.seed_runbooks(repo)), 4)
            book, rev = repo.get_draft("lab-recover-payment")
            book.name = "XPTO editado"
            repo.save_draft(book, "local-operator", rev)
            repo.archive("lab-inventory", "local-operator")
            repo.archive("lab-triage-batch", "local-operator", deleted=True)
            self.assertEqual(lab.seed_runbooks(repo), [])
            self.assertEqual(repo.get_draft(book.id)[0].name, "XPTO editado")
            self.assertEqual(repo.versions(book.id), [1])
            runtime = FlowOpsRuntime.local(repo, [local.local_context()])
            runtime.close()
            with (
                patch.object(lab, "seed_resources", return_value={}),
                patch.object(lab, "seed_runbooks", return_value=[]),
                patch.object(lab, "Repository"),
                patch("builtins.print"),
            ):
                lab.main()

    def test_seed_propagates_unexpected_errors_and_closes_clients(self) -> None:
        error = ClientError({"Error": {"Code": "AccessDenied"}}, "PutItem")
        with self.assertRaises(ClientError):
            lab._allow_error(MagicMock(side_effect=error), {"ResourceNotFoundException"})
        client = MagicMock()
        client.get_caller_identity.return_value = {"Account": "999999999999"}
        with (
            patch.object(lab, "local_client", return_value=client),
            self.assertRaisesRegex(ValueError, "account"),
        ):
            lab.seed_resources()
        self.assertEqual(client.close.call_count, 7)

    def test_actual_lambda_business_logic(self) -> None:
        event = {
            "payment": {"paymentId": {"S": "PAY-TEST"}, "amount": {"N": "149.90"}},
            "customer": {"customerId": {"S": "CUS-001"}, "active": {"BOOL": True}},
            "reason": "test",
            "execution_id": "exec",
        }
        self.assertEqual(handler(event, None)["event"]["amount"], "149.90")
        event["payment"]["amount"] = {"N": "5000.00"}
        self.assertEqual(handler(event, None)["event"]["priority"], "high")
        event["payment"]["amount"] = {"N": "0"}
        with self.assertRaisesRegex(ValueError, "positive"):
            handler(event, None)
        event["customer"]["active"] = {"BOOL": False}
        with self.assertRaisesRegex(ValueError, "Inactive"):
            handler(event, None)
        event["payment"]["forceFailure"] = {"BOOL": True}
        with self.assertRaisesRegex(ValueError, "Intentional"):
            handler(event, None)


@unittest.skipUnless(os.getenv("FLOWOPS_TEST_LOCAL_AWS") == "1", "Real Docker lab is opt-in")
class LocalBusinessJourneyTests(unittest.TestCase):
    def test_real_five_service_workflow_reuse_failures_and_seed_preservation(self) -> None:
        resources = lab.seed_resources()
        repo = Repository(lab.LAB_DATABASE_URL)
        lab.seed_runbooks(repo)
        backend = local.LocalAWSBackend([local.local_context()])
        engine = Engine(
            repo,
            build_registry(backend, catalog=ModelCatalog()),
            policy=PolicyEngine(two_person=False),
        )
        actor = Identity(id="local-operator", roles=["ADMIN"])
        clients = {name: local.local_client(name) for name in ("dynamodb", "sqs", "s3")}
        for client in clients.values():
            self.addCleanup(client.close)
        ddb, sqs, s3 = (clients[name] for name in ("dynamodb", "sqs", "s3"))

        def submit(
            book_id: str,
            parameters: dict | None = None,
            approve: bool = True,
            dry_run: bool = False,
        ):
            book = repo.version(book_id)
            values = {key: value.default for key, value in book.parameters.items()} | (
                parameters or {}
            )
            execution = engine.submit(
                book,
                actor,
                local.local_context(),
                values,
                token=new_id(),
                dry_run=dry_run,
                reason="Lab integration",
            )
            self.addCleanup(backend.release, execution.id)
            result = engine.execute(execution.id)
            while result.status == Status.WAITING_APPROVAL:
                gate = next(
                    a for a in engine.store.pending_approvals() if a["execution_id"] == result.id
                )
                engine.approve(
                    result.id,
                    gate["node_id"],
                    gate["digest"],
                    actor,
                    approved=approve,
                    reason="Lab review",
                )
                result = engine.execute(result.id)
            return result

        def status(payment_id: str) -> str:
            return ddb.get_item(TableName="flowops-payments", Key={"paymentId": {"S": payment_id}})[
                "Item"
            ]["status"]["S"]

        def count(queue: str) -> int:
            return int(
                sqs.get_queue_attributes(
                    QueueUrl=resources["queues"][queue],
                    AttributeNames=["ApproximateNumberOfMessages"],
                )["Attributes"]["ApproximateNumberOfMessages"]
            )

        inventory = submit("lab-inventory", dry_run=True)
        self.assertEqual(inventory.status, Status.SUCCESS, inventory.error)
        self.assertEqual(len(inventory.node_outputs["payments"]["Items"]), 8)
        self.assertEqual(len(inventory.node_outputs["merge"]), 6)
        triage = submit("lab-triage-batch")
        self.assertEqual(triage.status, Status.SUCCESS, triage.error)
        self.assertEqual(count("flowops-recovery-requests.fifo"), 4)
        self.assertEqual(len(triage.node_outputs["batch"]["batches"]), 2)
        dlq = submit("lab-redrive-dlq")
        self.assertEqual(dlq.status, Status.SUCCESS, dlq.error)
        self.assertEqual(count("flowops-payment-errors.fifo"), 0)
        self.assertEqual(count("flowops-recovery-requests.fifo"), 6)
        self.assertEqual(submit("lab-redrive-dlq").status, Status.SUCCESS)
        denied = submit("lab-recover-payment", {"payment_id": "PAY-1003"}, approve=False)
        self.assertNotEqual(denied.status, Status.SUCCESS)
        self.assertEqual(status("PAY-1003"), "PROCESSING")
        for payment_id in ("PAY-1001", "PAY-1002"):
            result = submit("lab-recover-payment", {"payment_id": payment_id})
            self.assertEqual(result.status, Status.SUCCESS, result.error)
            self.assertEqual(status(payment_id), "PROCESSED")
            self.assertEqual(
                result.node_outputs["prepare_event"]["Payload"]["event"]["payment_id"], payment_id
            )
            receipt = ddb.get_item(
                TableName="flowops-receipts", Key={"paymentId": {"S": payment_id}}
            )["Item"]
            self.assertEqual(receipt["executionId"]["S"], result.id)
            evidence = s3.get_object(
                Bucket="flowops-evidence", Key=f"recoveries/{payment_id}.json"
            )["Body"]
            try:
                self.assertEqual(json.loads(evidence.read())["execution_id"], result.id)
            finally:
                evidence.close()
        self.assertEqual(count("flowops-payment-events.fifo"), 2)
        self.assertEqual(count("flowops-notification-audit"), 2)
        replay = submit("lab-recover-payment", {"payment_id": "PAY-1001"})
        self.assertEqual(replay.status, Status.SUCCESS)
        self.assertIn("already_done", replay.node_outputs)
        self.assertEqual(count("flowops-payment-events.fifo"), 2)
        self.assertEqual(count("flowops-notification-audit"), 2)
        self.assertIn(
            "unsupported_status",
            submit("lab-recover-payment", {"payment_id": "PAY-3001"}).node_outputs,
        )
        for parameters, node in (
            ({"payment_id": "MISSING"}, "record_exists"),
            ({"payment_id": "PAY-4001"}, "active_customer"),
            ({"payment_id": "PAY-1003", "expected_status": "WRONG"}, "claim"),
            ({"payment_id": "PAY-5001"}, "report_failure"),
        ):
            result = submit("lab-recover-payment", parameters)
            self.assertEqual(result.status, Status.FAILED, (parameters, result.error))
            self.assertEqual(engine.store.nodes(result.id)[node]["status"], Status.FAILED)
        self.assertEqual(status("PAY-5001"), "PROCESSING")
        self.assertEqual(count("flowops-payment-events.fifo"), 2)
        bad_limit = submit("lab-triage-batch", {"limit": 1001})
        self.assertEqual(bad_limit.status, Status.FAILED)
        lab.seed_resources()
        self.assertEqual(status("PAY-1001"), "PROCESSED")
        self.assertEqual(count("flowops-payment-errors.fifo"), 0)
        self.assertEqual(count("flowops-notification-audit"), 2)
        self.assertEqual(lab.seed_runbooks(repo), [])
        self.assertEqual(
            Repository(lab.LAB_DATABASE_URL).version("lab-recover-payment").name,
            lab_runbooks()[0].name,
        )
        print(
            "LOCAL AWS PASS: PostgreSQL persistence, real Docker Lambda, DynamoDB/SQS/SNS/S3 effects, batch, DLQ, replay, approval rejection, missing record, inactive customer, conflict, compensation, bounded query and repeat setup"
        )
