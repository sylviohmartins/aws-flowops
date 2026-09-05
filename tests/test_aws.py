import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

from flowops.core.actions import ActionContext
from flowops.domain.errors import PolicyViolation, ProviderError, WorkflowValidationError
from flowops.domain.models import AWSContext
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import AWSAction, Limits, build_registry
from flowops.providers.aws.backend import BotoBackend, normalize_output, resource_scope
from flowops.providers.aws.catalog import CURATED, SPECS, ModelCatalog
from flowops.providers.aws.demo import DemoBackend

HAS_BOTO = importlib.util.find_spec("boto3") is not None


class AWSAdapterTests(unittest.TestCase):
    def test_curated_coverage_and_mutation_classification(self) -> None:
        self.assertGreaterEqual(len(CURATED), 60)
        for key in ["lambda.invoke", "sqs.receive_message", "sqs.purge_queue", "dynamodb.execute_statement"]:
            self.assertFalse(SPECS[key].read_only)
            self.assertFalse(SPECS[key].idempotent)

    def test_stream_is_bounded_and_closed(self) -> None:
        stream = io.BytesIO(b"x" * 100)
        self.assertTrue(normalize_output(stream, 10)["_truncated"])
        self.assertTrue(stream.closed)
        self.assertEqual(normalize_output(io.BytesIO(b'{"ok":true}'), 100), {"ok": True})

    def test_account_region_and_endpoint_guards(self) -> None:
        context = AWSContext(account_id="123456789012")
        resource_scope({"QueueUrl": "https://sqs.sa-east-1.amazonaws.com/123456789012/queue"}, context)
        for value in ["http://169.254.169.254/latest", "https://sqs.sa-east-1.amazonaws.com/999999999999/queue", "https://sqs.sa-east-1.amazonaws.com.evil.test/123456789012/queue"]:
            with self.assertRaises(PolicyViolation):
                resource_scope({"QueueUrl": value}, context)
        with self.assertRaises(PolicyViolation):
            resource_scope({"FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:other"}, context)

    def test_demo_is_explicit_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Repository(Path(temp) / "test.db")
            backend = DemoBackend(repo)
            registry = build_registry(backend)
            context = ActionContext("execution", "get", AWSContext(), False)
            output = registry.get("dynamodb.get_item").execute({"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}}, context)
            self.assertEqual(output["Item"]["status"]["S"], "PROCESSING")
            self.assertTrue(output["_demo"])
            with self.assertRaises(ProviderError):
                registry.get("sqs.purge_queue").execute({}, context)
            action = registry.get("dynamodb.scan")
            with self.assertRaises(PolicyViolation):
                action.validate({"TableName": "payments", "Limit": 100000})

    def test_partial_failure_is_not_success(self) -> None:
        class Partial:
            def invoke(self, service: str, operation: str, parameters: dict[str, Any], context: ActionContext, limits: Limits) -> Any:
                return {"Failed": [{"Id": "one", "Code": "Denied"}]}

        action = AWSAction(SPECS["sqs.send_message_batch"], Partial())
        with self.assertRaises(ProviderError) as caught:
            action.execute({"Entries": []}, ActionContext("one", "call", AWSContext(), False))
        self.assertEqual(caught.exception.code, "PartialFailure")


@unittest.skipUnless(HAS_BOTO, "botocore not installed locally; run in dependency-enabled CI")
class BotocoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        import boto3
        from botocore.config import Config
        from botocore.stub import Stubber

        self.catalog = ModelCatalog()
        self.aws = AWSContext(mode="aws", account_id="123456789012")
        self.context = ActionContext("contract", "call", self.aws, False)
        self.session = boto3.Session(aws_access_key_id="test", aws_secret_access_key="test", region_name="sa-east-1")
        self.client = self.session.client("dynamodb", config=Config(retries={"total_max_attempts": 1}))
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.backend = BotoBackend([self.aws])
        self.backend._client = lambda service, context: self.client

    def test_all_curated_operations_exist_in_sdk(self) -> None:
        for spec in CURATED:
            with self.subTest(action=spec.id):
                action = AWSAction(spec, self.backend, self.catalog)
                self.assertEqual(action.metadata.id, spec.id)

    def test_get_item_stubber_and_parameter_types(self) -> None:
        params = {"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}}
        self.stub.add_response("get_item", {"Item": {"status": {"S": "PROCESSING"}}}, params)
        action = AWSAction(SPECS["dynamodb.get_item"], self.backend, self.catalog)
        action.validate(params)
        self.assertEqual(action.execute(params, self.context)["Item"]["status"]["S"], "PROCESSING")
        self.stub.assert_no_pending_responses()
        with self.assertRaises(WorkflowValidationError):
            action.validate({"TableName": 42})

    def test_access_denied_does_not_leak_message(self) -> None:
        self.stub.add_client_error("get_item", service_error_code="AccessDeniedException", service_message="secret sensitive detail", expected_params={"TableName": "payments", "Key": {"paymentId": {"S": "1"}}})
        action = AWSAction(SPECS["dynamodb.get_item"], self.backend, self.catalog)
        with self.assertRaises(ProviderError) as caught:
            action.execute({"TableName": "payments", "Key": {"paymentId": {"S": "1"}}}, self.context)
        self.assertEqual(str(caught.exception), "AccessDeniedException")

    def test_generic_default_deny_and_conservative_risk(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.catalog.generic_spec("ec2", "describe_instances", set())
        spec = self.catalog.generic_spec("ec2", "describe_instances", {"ec2.describe_instances"})
        self.assertFalse(spec.read_only)
        with self.assertRaises(PolicyViolation):
            self.catalog.generic_spec("iam", "create_user", {"iam.create_user"})
