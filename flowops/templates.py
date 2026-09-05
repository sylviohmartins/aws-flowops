"""Curated runbook templates; definitions remain ordinary versioned Runbook models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from flowops.domain.models import Edge, Node, Parameter, Runbook


@dataclass(frozen=True)
class RunbookTemplate:
    id: str
    name: str
    description: str
    factory: Callable[[str, str], Runbook]
    demo_compatible: bool = True

    def create(self, owner: str, team: str) -> Runbook:
        return self.factory(owner, team)


def _base(name: str, description: str, owner: str, team: str) -> Runbook:
    return Runbook(
        name=name,
        description=description,
        owner=owner,
        team=team,
        environments=["dev", "staging", "production"],
    )


def blank(owner: str, team: str) -> Runbook:
    book = _base("New Runbook", "Blank visual runbook", owner, team)
    book.nodes = [
        Node(id="start", action="core.start", label="Start", position=(40, 180)),
        Node(id="end", action="core.end", label="End", position=(420, 180)),
    ]
    book.edges = [Edge(source="start", target="end")]
    return book


def fix_stuck_payment(owner: str, team: str) -> Runbook:
    book = _base(
        "Fix Stuck Payment",
        "Safely recover one payment stuck in PROCESSING, emit an event and verify completion.",
        owner,
        team,
    )
    book.tags = ["payments", "recovery", "demo"]
    book.parameters = {
        "payment_id": Parameter(type="string", description="Payment identifier"),
        "environment": Parameter(type="string", description="Must match the execution environment"),
    }
    book.nodes = [
        Node(id="start", action="core.start", label="Start", position=(40, 180)),
        Node(
            id="environment_match",
            action="core.validation",
            label="Validate Environment",
            config={"left": "{{ params.environment }}", "right": "{{ context.environment }}"},
            position=(260, 180),
        ),
        Node(
            id="get_before",
            action="dynamodb.get_item",
            label="DynamoDB GetItem",
            config={
                "TableName": "payments",
                "Key": {"paymentId": {"S": "{{ params.payment_id }}"}},
            },
            position=(500, 180),
        ),
        Node(
            id="is_processing",
            action="core.condition",
            label="status == PROCESSING",
            config={
                "left": "{{ nodes.get_before.output.Item.status.S }}",
                "right": "PROCESSING",
            },
            position=(740, 180),
        ),
        Node(
            id="approve",
            action="core.approval",
            label="Manual Approval",
            config={"message": "Approve conditional payment recovery"},
            position=(980, 80),
        ),
        Node(
            id="update_status",
            action="dynamodb.update_item",
            label="DynamoDB UpdateItem",
            config={
                "TableName": "payments",
                "Key": {"paymentId": {"S": "{{ params.payment_id }}"}},
                "ConditionExpression": "#s = :expected",
                "UpdateExpression": "SET #s = :next",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {
                    ":expected": {"S": "PROCESSING"},
                    ":next": {"S": "RETRY_REQUESTED"},
                },
                "ReturnValues": "ALL_NEW",
            },
            position=(1220, 80),
        ),
        Node(
            id="send_event",
            action="sqs.send_message",
            label="SQS SendMessage",
            config={
                "QueueUrl": "https://sqs.{{ context.region }}.amazonaws.com/{{ context.account }}/payments-events",
                "MessageBody": {
                    "payment_id": "{{ params.payment_id }}",
                    "source": "flowops",
                },
            },
            position=(1460, 80),
        ),
        Node(
            id="wait_processing",
            action="core.wait",
            label="Wait",
            config={"seconds": 1},
            position=(1700, 80),
        ),
        Node(
            id="get_after",
            action="dynamodb.get_item",
            label="Verify DynamoDB",
            config={
                "TableName": "payments",
                "Key": {"paymentId": {"S": "{{ params.payment_id }}"}},
            },
            position=(1940, 80),
        ),
        Node(
            id="validate_done",
            action="core.validation",
            label="Validate PROCESSED",
            config={
                "left": "{{ nodes.get_after.output.Item.status.S }}",
                "right": "PROCESSED",
            },
            position=(2180, 80),
        ),
        Node(id="end", action="core.end", label="End", position=(2420, 180)),
    ]
    book.edges = [
        Edge(source="start", target="environment_match"),
        Edge(source="environment_match", target="get_before"),
        Edge(source="get_before", target="is_processing"),
        Edge(source="is_processing", target="approve", branch="true"),
        Edge(source="is_processing", target="end", branch="false"),
        Edge(source="approve", target="update_status"),
        Edge(source="update_status", target="send_event"),
        Edge(source="send_event", target="wait_processing"),
        Edge(source="wait_processing", target="get_after"),
        Edge(source="get_after", target="validate_done"),
        Edge(source="validate_done", target="end"),
    ]
    return book


def lambda_invoke(owner: str, team: str) -> Runbook:
    book = _base("Lambda Invoke", "Invoke a Lambda with an explicit payload.", owner, team)
    book.parameters = {
        "function_name": Parameter(type="string"),
        "payload": Parameter(type="object", default={}, required=False),
    }
    book.nodes = [
        Node(id="start", action="core.start", position=(40, 120)),
        Node(
            id="invoke",
            action="lambda.invoke",
            config={
                "FunctionName": "{{ params.function_name }}",
                "Payload": "{{ params.payload }}",
            },
            position=(280, 120),
        ),
        Node(id="end", action="core.end", position=(520, 120)),
    ]
    book.edges = [Edge(source="start", target="invoke"), Edge(source="invoke", target="end")]
    return book


def replay_event(owner: str, team: str) -> Runbook:
    book = _base("Replay Event", "Publish a controlled message to an SQS queue.", owner, team)
    book.parameters = {
        "queue_url": Parameter(type="string"),
        "message": Parameter(type="object"),
    }
    book.nodes = [
        Node(id="start", action="core.start", position=(40, 120)),
        Node(
            id="send",
            action="sqs.send_message",
            config={"QueueUrl": "{{ params.queue_url }}", "MessageBody": "{{ params.message }}"},
            position=(280, 120),
        ),
        Node(id="end", action="core.end", position=(520, 120)),
    ]
    book.edges = [Edge(source="start", target="send"), Edge(source="send", target="end")]
    return book


def dynamodb_record_correction(owner: str, team: str) -> Runbook:
    book = _base(
        "DynamoDB Record Correction",
        "Read a record, require approval, then perform a parameterized UpdateItem request.",
        owner,
        team,
    )
    book.parameters = {
        "table_name": Parameter(type="string"),
        "key": Parameter(type="object"),
        "update_expression": Parameter(type="string"),
        "expression_names": Parameter(type="object"),
        "expression_values": Parameter(type="object"),
    }
    book.nodes = [
        Node(id="start", action="core.start", position=(40, 120)),
        Node(
            id="read",
            action="dynamodb.get_item",
            config={"TableName": "{{ params.table_name }}", "Key": "{{ params.key }}"},
            position=(280, 120),
        ),
        Node(id="approve", action="core.approval", position=(520, 120)),
        Node(
            id="update",
            action="dynamodb.update_item",
            config={
                "TableName": "{{ params.table_name }}",
                "Key": "{{ params.key }}",
                "UpdateExpression": "{{ params.update_expression }}",
                "ExpressionAttributeNames": "{{ params.expression_names }}",
                "ExpressionAttributeValues": "{{ params.expression_values }}",
                "ReturnValues": "ALL_NEW",
            },
            position=(760, 120),
        ),
        Node(id="end", action="core.end", position=(1000, 120)),
    ]
    book.edges = [
        Edge(source="start", target="read"),
        Edge(source="read", target="approve"),
        Edge(source="approve", target="update"),
        Edge(source="update", target="end"),
    ]
    return book


TEMPLATES = {
    template.id: template
    for template in [
        RunbookTemplate("blank", "Blank Runbook", "Start and End canvas", blank),
        RunbookTemplate(
            "fix-stuck-payment",
            "Fix Stuck Payment",
            "DynamoDB + approval + SQS + verification",
            fix_stuck_payment,
        ),
        RunbookTemplate("lambda-invoke", "Lambda Invoke", "Invoke a Lambda safely", lambda_invoke),
        RunbookTemplate("replay-event", "Replay Event", "Send an SQS event", replay_event),
        RunbookTemplate(
            "dynamodb-record-correction",
            "DynamoDB Record Correction",
            "Read, approve and update a record",
            dynamodb_record_correction,
            demo_compatible=False,
        ),
    ]
}
