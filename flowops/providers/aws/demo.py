"""Explicit, durable demo backend. Unsupported calls are errors, never fabricated successes."""

import json
from typing import Any

from flowops.core.actions import ActionContext
from flowops.domain.errors import ProviderError
from flowops.persistence.repository import Repository, canonical
from flowops.providers.aws.actions import Limits

SUPPORTED = {
    "dynamodb.list_tables",
    "dynamodb.describe_table",
    "dynamodb.get_item",
    "dynamodb.query",
    "dynamodb.scan",
    "dynamodb.update_item",
    "sqs.list_queues",
    "sqs.send_message",
    "sqs.get_queue_attributes",
    "lambda.list_functions",
    "lambda.get_function_configuration",
    "lambda.invoke",
    "sns.list_topics",
    "sns.publish",
    "s3.list_buckets",
    "s3.list_objects_v2",
    "s3.put_object",
    "s3.get_object",
}


class DemoBackend:
    """A payment fixture plus a synchronous, clearly simulated SQS consumer."""

    def __init__(self, repository: Repository):
        self.repository = repository
        with repository.transaction() as db:
            exists = db.execute("SELECT id FROM resource_bindings WHERE id='demo-state'").fetchone()
            if exists is None:
                db.execute(
                    "INSERT INTO resource_bindings VALUES (?,?)",
                    ("demo-state", canonical(self.initial_state())),
                )

    @staticmethod
    def initial_state() -> dict[str, Any]:
        return {
            "payments": {
                key: {"paymentId": {"S": key}, "status": {"S": "PROCESSING"}}
                for key in ["12345", "23456", "34567"]
            },
            "messages": [],
            "objects": {},
        }

    def reset(self) -> None:
        with self.repository.transaction() as db:
            db.execute(
                "UPDATE resource_bindings SET body=? WHERE id='demo-state'",
                (canonical(self.initial_state()),),
            )

    def invoke(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any:
        if context.aws.mode != "demo":
            raise ProviderError("Demo backend cannot execute a live AWS context")
        key = f"{service}.{operation}"
        if key not in SUPPORTED:
            raise ProviderError(
                f"DemoUnsupportedOperation: {key}; select a configured real AWS context"
            )
        with self.repository.transaction() as db:
            state = json.loads(
                db.execute("SELECT body FROM resource_bindings WHERE id='demo-state'").fetchone()[0]
            )
            result = self._call(key, parameters, state, context, limits)
            db.execute(
                "UPDATE resource_bindings SET body=? WHERE id='demo-state'", (canonical(state),)
            )
        return result | {
            "ResponseMetadata": {
                "RequestId": f"demo-{context.execution_id}-{context.node_id}",
                "HTTPStatusCode": 200,
            },
            "_demo": True,
        }

    def _call(
        self,
        key: str,
        p: dict[str, Any],
        state: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> dict[str, Any]:
        account, region = context.aws.account_id, context.aws.region
        queue = f"https://sqs.{region}.amazonaws.com/{account}/payments-events"
        if key == "dynamodb.list_tables":
            return {"TableNames": ["payments"]}
        if key.startswith("dynamodb."):
            if p.get("TableName") != "payments":
                raise ProviderError("ResourceNotFoundException")
            if key == "dynamodb.describe_table":
                return {
                    "Table": {
                        "TableName": "payments",
                        "KeySchema": [{"AttributeName": "paymentId", "KeyType": "HASH"}],
                        "TableStatus": "ACTIVE",
                    }
                }
            if key in {"dynamodb.query", "dynamodb.scan"}:
                items = list(state["payments"].values())
                if key == "dynamodb.query":
                    target = p.get("ExpressionAttributeValues", {}).get(":paymentId", {}).get("S")
                    items = [i for i in items if i["paymentId"]["S"] == target]
                return {
                    "Items": items[: min(p.get("Limit", limits.max_items), limits.max_items)],
                    "Count": len(items),
                }
            payment_id = p["Key"]["paymentId"]["S"]
            item = state["payments"].get(payment_id)
            if key == "dynamodb.get_item":
                return {"Item": item} if item else {}
            if item is None:
                raise ProviderError("ResourceNotFoundException")
            values = p.get("ExpressionAttributeValues", {})
            if (
                p.get("ConditionExpression") != "#s = :expected"
                or p.get("UpdateExpression") != "SET #s = :next"
                or p.get("ExpressionAttributeNames") != {"#s": "status"}
            ):
                raise ProviderError("Demo supports the documented conditional status update only")
            if item["status"] != values.get(":expected"):
                raise ProviderError("ConditionalCheckFailedException")
            item["status"] = values[":next"]
            return {"Attributes": item}
        if key == "sqs.list_queues":
            return {"QueueUrls": [queue]}
        if key == "sqs.get_queue_attributes":
            return {"Attributes": {"ApproximateNumberOfMessages": str(len(state["messages"]))}}
        if key == "sqs.send_message":
            if p.get("QueueUrl") != queue:
                raise ProviderError("AWS.SimpleQueueService.NonExistentQueue")
            message = json.loads(p["MessageBody"])
            state["messages"].append(message)
            payment_id = message.get("payment_id")
            if payment_id in state["payments"]:
                state["payments"][payment_id]["status"] = {"S": "PROCESSED"}
            return {
                "MessageId": f"demo-message-{len(state['messages'])}",
                "MD5OfMessageBody": "demo-only",
            }
        if key == "lambda.list_functions":
            return {"Functions": [{"FunctionName": "payment-processor", "Runtime": "python3.12"}]}
        if key == "lambda.get_function_configuration":
            return {
                "FunctionName": p["FunctionName"],
                "Runtime": "python3.12",
                "PackageType": "Zip",
                "RevisionId": "demo-revision",
            }
        if key == "lambda.invoke":
            return {
                "StatusCode": 200,
                "Payload": {"accepted": True, "payload": json.loads(p.get("Payload", "{}"))},
            }
        if key == "sns.list_topics":
            return {"Topics": [{"TopicArn": f"arn:aws:sns:{region}:{account}:payments"}]}
        if key == "sns.publish":
            return {"MessageId": f"demo-notification-{context.execution_id}"}
        if key == "s3.list_buckets":
            return {"Buckets": [{"Name": "flowops-demo"}]}
        if key == "s3.list_objects_v2":
            return {"Contents": [{"Key": k} for k in state["objects"]]}
        if key == "s3.put_object":
            state["objects"][p["Key"]] = p.get("Body", "")
            return {"ETag": "demo-etag"}
        if p["Key"] not in state["objects"]:
            raise ProviderError("NoSuchKey")
        return {"Body": state["objects"][p["Key"]]}
