"""Explicit local-only provisioning. Never called by Streamlit render/rerun."""

import io
import json
import zipfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from flowops.core.graph import validate_graph
from flowops.lab_templates import lab_runbooks
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import build_registry
from flowops.providers.aws.catalog import ModelCatalog
from flowops.providers.aws.local import LOCAL_ACCOUNT, LocalAWSBackend, local_client, local_context

LAB_DATABASE_URL = "postgresql://flowops_local:flowops_local@127.0.0.1:55432/flowops_local"


def _allow_error(call: Any, codes: set[str], **kwargs: Any) -> Any:
    from botocore.exceptions import ClientError

    try:
        return call(**kwargs)
    except ClientError as error:
        if error.response["Error"]["Code"] not in codes:
            raise
        return None


def seed_resources() -> dict[str, Any]:
    """Create missing resources/fixtures; never overwrite operator data or Lambda code."""
    with ExitStack() as stack:
        clients = {
            name: local_client(name)
            for name in ("sts", "dynamodb", "sqs", "sns", "s3", "iam", "lambda")
        }
        for client in clients.values():
            stack.callback(client.close)
        if clients["sts"].get_caller_identity()["Account"] != LOCAL_ACCOUNT:
            raise ValueError("Unexpected local emulator account")
        ddb, sqs, sns, s3 = (clients[name] for name in ("dynamodb", "sqs", "sns", "s3"))
        for table, key in (
            ("flowops-payments", "paymentId"),
            ("flowops-customers", "customerId"),
            ("flowops-receipts", "paymentId"),
            ("flowops-lab-seed", "id"),
        ):
            options: dict[str, Any] = {
                "TableName": table,
                "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
                "AttributeDefinitions": [{"AttributeName": key, "AttributeType": "S"}],
                "BillingMode": "PAY_PER_REQUEST",
            }
            if table == "flowops-payments":
                options["AttributeDefinitions"].append(
                    {"AttributeName": "status", "AttributeType": "S"}
                )
                options["GlobalSecondaryIndexes"] = [
                    {
                        "IndexName": "status-index",
                        "KeySchema": [
                            {"AttributeName": "status", "KeyType": "HASH"},
                            {"AttributeName": key, "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ]
            _allow_error(ddb.create_table, {"ResourceInUseException"}, **options)
        for customer_id, active in (("CUS-001", True), ("CUS-002", True), ("CUS-003", False)):
            _allow_error(
                ddb.put_item,
                {"ConditionalCheckFailedException"},
                TableName="flowops-customers",
                Item={
                    "customerId": {"S": customer_id},
                    "name": {"S": f"Cliente fictício {customer_id}"},
                    "active": {"BOOL": active},
                },
                ConditionExpression="attribute_not_exists(customerId)",
            )
        for payment_id, customer_id, status, amount, failure in [
            ("PAY-1001", "CUS-001", "PROCESSING", "149.90", False),
            ("PAY-1002", "CUS-002", "PROCESSING", "7200.00", False),
            ("PAY-1003", "CUS-001", "PROCESSING", "89.50", False),
            ("PAY-1004", "CUS-001", "PROCESSING", "250.00", False),
            ("PAY-2001", "CUS-001", "PROCESSED", "99.00", False),
            ("PAY-3001", "CUS-002", "CANCELLED", "100.00", False),
            ("PAY-4001", "CUS-003", "PROCESSING", "200.00", False),
            ("PAY-5001", "CUS-001", "PROCESSING", "300.00", True),
        ]:
            item = {
                "paymentId": {"S": payment_id},
                "customerId": {"S": customer_id},
                "status": {"S": status},
                "amount": {"N": amount},
                "forceFailure": {"BOOL": failure},
            }
            _allow_error(
                ddb.put_item,
                {"ConditionalCheckFailedException"},
                TableName="flowops-payments",
                Item=item,
                ConditionExpression="attribute_not_exists(paymentId)",
            )
        queues = {}
        for name in (
            "flowops-payment-events.fifo",
            "flowops-recovery-requests.fifo",
            "flowops-payment-errors.fifo",
            "flowops-notification-audit",
        ):
            queues[name] = sqs.create_queue(
                QueueName=name, Attributes={"FifoQueue": "true"} if name.endswith(".fifo") else {}
            )["QueueUrl"]
        topic = sns.create_topic(Name="flowops-payment-notifications")["TopicArn"]
        audit_arn = sqs.get_queue_attributes(
            QueueUrl=queues["flowops-notification-audit"], AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        sqs.set_queue_attributes(
            QueueUrl=queues["flowops-notification-audit"],
            Attributes={
                "Policy": json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "sns.amazonaws.com"},
                                "Action": "sqs:SendMessage",
                                "Resource": audit_arn,
                                "Condition": {"ArnEquals": {"aws:SourceArn": topic}},
                            }
                        ],
                    }
                )
            },
        )
        sns.subscribe(
            TopicArn=topic,
            Protocol="sqs",
            Endpoint=audit_arn,
            Attributes={"RawMessageDelivery": "true"},
        )
        _allow_error(
            s3.create_bucket,
            {"BucketAlreadyOwnedByYou"},
            Bucket="flowops-evidence",
            CreateBucketConfiguration={"LocationConstraint": "sa-east-1"},
        )
        role = f"arn:aws:iam::{LOCAL_ACCOUNT}:role/flowops-local-lambda"
        _allow_error(
            clients["iam"].create_role,
            {"EntityAlreadyExists"},
            RoleName="flowops-local-lambda",
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("handler.py", Path(__file__).with_name("lab_lambda.py").read_bytes())
        _allow_error(
            clients["lambda"].create_function,
            {"ResourceConflictException"},
            FunctionName="flowops-prepare-payment",
            Runtime="python3.12",
            Role=role,
            Handler="handler.handler",
            Code={"ZipFile": archive.getvalue()},
            Timeout=20,
            MemorySize=128,
        )
        # Mark only after writes. FIFO IDs also deduplicate a retry during partial seeding.
        marker = ddb.get_item(TableName="flowops-lab-seed", Key={"id": {"S": "fixtures-v1"}})
        if "Item" not in marker:
            for payment_id in ("PAY-1003", "PAY-5001"):
                sqs.send_message(
                    QueueUrl=queues["flowops-payment-errors.fifo"],
                    MessageBody=json.dumps(
                        {"payment_id": payment_id, "operation": "recover", "source": "seed-dlq"}
                    ),
                    MessageGroupId="fixtures",
                    MessageDeduplicationId=payment_id,
                )
            _allow_error(
                s3.put_object,
                {"PreconditionFailed"},
                Bucket="flowops-evidence",
                Key="README.json",
                Body=json.dumps(
                    {"lab": "AWS FlowOps", "data": "fictitious", "automatic_consumers": False}
                ),
                ContentType="application/json",
                IfNoneMatch="*",
            )
            ddb.put_item(TableName="flowops-lab-seed", Item={"id": {"S": "fixtures-v1"}})
        return {
            "queues": queues,
            "topic": topic,
            "bucket": "flowops-evidence",
            "function": "flowops-prepare-payment",
        }


def seed_runbooks(repository: Repository) -> list[str]:
    registry = build_registry(LocalAWSBackend([local_context()]), catalog=ModelCatalog())
    existing = {
        book.id
        for archived in (False, True)
        for book in repository.list_runbooks(archived=archived)
    }
    created = []
    for book in lab_runbooks():
        validate_graph(book, registry)
        if book.id not in existing and not repository.versions(book.id):
            revision = repository.save_draft(book, "local-operator")
            repository.publish(book.id, "local-operator", revision)
            created.append(book.id)
    return created


def main() -> None:
    resources = seed_resources()
    created = seed_runbooks(Repository(LAB_DATABASE_URL))
    print(
        json.dumps({"resources": resources, "new_runbooks": created}, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
