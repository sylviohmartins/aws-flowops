from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from flowops.core.actions import ActionContext
from flowops.domain.errors import ProviderError
from flowops.domain.models import AWSContext
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import Limits
from flowops.providers.aws.demo import DemoBackend


def context(
    execution_id: str = "run",
    node_id: str = "node",
    *,
    dry_run: bool = False,
    mode: str = "demo",
) -> ActionContext:
    return ActionContext(
        execution_id,
        node_id,
        AWSContext(mode=mode),  # type: ignore[arg-type]
        dry_run,
    )


def invoke(
    backend: DemoBackend,
    service: str,
    operation: str,
    parameters: dict,
    *,
    execution_id: str = "run",
    dry_run: bool = False,
):
    return backend.invoke(
        service,
        operation,
        parameters,
        context(execution_id, dry_run=dry_run),
        Limits(),
    )


def test_demo_backend_full_operation_surface_and_errors() -> None:
    with tempfile.TemporaryDirectory() as temp:
        repo = Repository(Path(temp) / "demo.db")
        backend = DemoBackend(repo)

        tables = invoke(backend, "dynamodb", "list_tables", {})
        assert tables["TableNames"] == ["payments"]
        assert tables["_demo"] is True

        with pytest.raises(ProviderError, match="live AWS context"):
            backend.invoke(
                "dynamodb",
                "list_tables",
                {},
                context(mode="aws"),
                Limits(),
            )
        with pytest.raises(ProviderError, match="DemoUnsupportedOperation"):
            invoke(backend, "sqs", "purge_queue", {})
        with pytest.raises(ProviderError, match="ResourceNotFoundException"):
            invoke(backend, "dynamodb", "describe_table", {"TableName": "missing"})

        described = invoke(
            backend,
            "dynamodb",
            "describe_table",
            {"TableName": "payments"},
        )
        assert described["Table"]["TableStatus"] == "ACTIVE"

        scan = invoke(
            backend,
            "dynamodb",
            "scan",
            {"TableName": "payments", "Limit": 2},
        )
        assert scan["Count"] == 3
        assert len(scan["Items"]) == 2
        query = invoke(
            backend,
            "dynamodb",
            "query",
            {
                "TableName": "payments",
                "ExpressionAttributeValues": {":paymentId": {"S": "23456"}},
                "Limit": 100,
            },
        )
        assert query["Count"] == 1
        assert query["Items"][0]["paymentId"]["S"] == "23456"

        existing = invoke(
            backend,
            "dynamodb",
            "get_item",
            {"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}},
        )
        assert existing["Item"]["status"]["S"] == "PROCESSING"
        missing = invoke(
            backend,
            "dynamodb",
            "get_item",
            {"TableName": "payments", "Key": {"paymentId": {"S": "99999"}}},
        )
        assert "Item" not in missing

        with pytest.raises(ProviderError, match="ResourceNotFoundException"):
            invoke(
                backend,
                "dynamodb",
                "update_item",
                {
                    "TableName": "payments",
                    "Key": {"paymentId": {"S": "99999"}},
                },
            )
        with pytest.raises(ProviderError, match="documented conditional status update"):
            invoke(
                backend,
                "dynamodb",
                "update_item",
                {
                    "TableName": "payments",
                    "Key": {"paymentId": {"S": "12345"}},
                    "UpdateExpression": "SET nope = :x",
                },
            )

        update = {
            "TableName": "payments",
            "Key": {"paymentId": {"S": "12345"}},
            "ConditionExpression": "#s = :expected",
            "UpdateExpression": "SET #s = :next",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {
                ":expected": {"S": "PROCESSING"},
                ":next": {"S": "RETRY_REQUESTED"},
            },
        }
        changed = invoke(backend, "dynamodb", "update_item", update)
        assert changed["Attributes"]["status"]["S"] == "RETRY_REQUESTED"
        with pytest.raises(ProviderError, match="ConditionalCheckFailedException"):
            invoke(backend, "dynamodb", "update_item", update)

        queues = invoke(backend, "sqs", "list_queues", {})
        queue = queues["QueueUrls"][0]
        assert "/000000000000/payments-events" in queue
        attributes = invoke(
            backend,
            "sqs",
            "get_queue_attributes",
            {"QueueUrl": queue},
        )
        assert attributes["Attributes"]["ApproximateNumberOfMessages"] == "0"
        with pytest.raises(ProviderError, match="NonExistentQueue"):
            invoke(
                backend,
                "sqs",
                "send_message",
                {"QueueUrl": "https://example.test/q", "MessageBody": "{}"},
            )
        sent = invoke(
            backend,
            "sqs",
            "send_message",
            {
                "QueueUrl": queue,
                "MessageBody": '{"payment_id":"23456"}',
            },
        )
        assert sent["MessageId"] == "demo-message-1"
        processed = invoke(
            backend,
            "dynamodb",
            "get_item",
            {"TableName": "payments", "Key": {"paymentId": {"S": "23456"}}},
        )
        assert processed["Item"]["status"]["S"] == "PROCESSED"

        functions = invoke(backend, "lambda", "list_functions", {})
        assert functions["Functions"][0]["FunctionName"] == "payment-processor"
        configuration = invoke(
            backend,
            "lambda",
            "get_function_configuration",
            {"FunctionName": "payment-processor"},
        )
        assert configuration["RevisionId"] == "demo-revision"
        invoked = invoke(
            backend,
            "lambda",
            "invoke",
            {"FunctionName": "payment-processor", "Payload": '{"x":1}'},
        )
        assert invoked["Payload"] == {"accepted": True, "payload": {"x": 1}}

        topics = invoke(backend, "sns", "list_topics", {})
        assert topics["Topics"][0]["TopicArn"].endswith(":payments")
        notification = invoke(
            backend,
            "sns",
            "publish",
            {"TopicArn": topics["Topics"][0]["TopicArn"], "Message": "ok"},
        )
        assert notification["MessageId"] == "demo-notification-run"

        buckets = invoke(backend, "s3", "list_buckets", {})
        assert buckets["Buckets"] == [{"Name": "flowops-demo"}]
        assert (
            invoke(
                backend,
                "s3",
                "list_objects_v2",
                {"Bucket": "flowops-demo"},
            )["Contents"]
            == []
        )
        put = invoke(
            backend,
            "s3",
            "put_object",
            {"Bucket": "flowops-demo", "Key": "one.txt", "Body": "hello"},
        )
        assert put["ETag"] == "demo-etag"
        objects = invoke(
            backend,
            "s3",
            "list_objects_v2",
            {"Bucket": "flowops-demo"},
        )
        assert objects["Contents"] == [{"Key": "one.txt"}]
        got = invoke(
            backend,
            "s3",
            "get_object",
            {"Bucket": "flowops-demo", "Key": "one.txt"},
        )
        assert got["Body"] == "hello"
        with pytest.raises(ProviderError, match="NoSuchKey"):
            invoke(
                backend,
                "s3",
                "get_object",
                {"Bucket": "flowops-demo", "Key": "missing"},
            )


def test_demo_preview_dry_run_isolation_eviction_and_reset() -> None:
    with tempfile.TemporaryDirectory() as temp:
        repo = Repository(Path(temp) / "demo.db")
        backend = DemoBackend(repo)
        queue = "https://sqs.sa-east-1.amazonaws.com/000000000000/payments-events"

        preview = backend.preview(
            "sqs",
            "send_message",
            {"QueueUrl": queue, "MessageBody": '{"payment_id":"12345"}'},
            context("preview"),
            Limits(),
        )
        assert preview["_demo"] is True
        simulated = invoke(
            backend,
            "dynamodb",
            "get_item",
            {"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}},
            execution_id="preview",
            dry_run=True,
        )
        assert simulated["Item"]["status"]["S"] == "PROCESSED"
        persisted = invoke(
            backend,
            "dynamodb",
            "get_item",
            {"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}},
            execution_id="actual",
        )
        assert persisted["Item"]["status"]["S"] == "PROCESSING"

        for index in range(101):
            backend._simulation(f"sim-{index}")
        assert len(backend.simulations) == 100
        assert "sim-0" not in backend.simulations

        invoke(
            backend,
            "s3",
            "put_object",
            {"Bucket": "flowops-demo", "Key": "dirty", "Body": "x"},
        )
        backend.reset()
        assert backend.simulations == {}
        objects = invoke(
            backend,
            "s3",
            "list_objects_v2",
            {"Bucket": "flowops-demo"},
        )
        assert objects["Contents"] == []
