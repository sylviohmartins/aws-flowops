"""Bounded SQS copy-and-ack action. Receipt handles never leave provider memory."""

from typing import Any
from urllib.parse import urlparse

from flowops.core.actions import ActionContext, Metadata
from flowops.domain.errors import ProviderError, WorkflowValidationError
from flowops.domain.models import Risk
from flowops.providers.aws.actions import AWSAction, Backend
from flowops.providers.aws.catalog import SPECS, ModelCatalog


class RedriveMessages:
    def __init__(self, backend: Backend, catalog: ModelCatalog | None = None):
        self.backend = backend
        self.actions = {
            operation: AWSAction(SPECS[f"sqs.{operation}"], backend, catalog)
            for operation in ("receive_message", "send_message", "delete_message")
        }
        self.metadata = Metadata(
            "sqs.redrive_messages",
            "aws",
            "sqs",
            "redrive_messages",
            "Copy up to 10 SQS messages and acknowledge originals after all sends succeed",
            risk=Risk.HIGH,
            read_only=False,
            idempotent=False,
            required_permissions=("sqs:ReceiveMessage", "sqs:SendMessage", "sqs:DeleteMessage"),
            input_schema={
                "type": "object",
                "required": ["SourceQueueUrl", "DestinationQueueUrl"],
                "properties": {
                    "SourceQueueUrl": {"type": "string"},
                    "DestinationQueueUrl": {"type": "string"},
                    "MaxMessages": {"type": "integer", "default": 3},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "received": {"type": "integer"},
                    "sent": {"type": "integer"},
                    "deleted": {"type": "integer"},
                    "message_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        )

    def validate(self, config: dict[str, Any]) -> None:
        if config.keys() - {"SourceQueueUrl", "DestinationQueueUrl", "MaxMessages"}:
            raise WorkflowValidationError("Unknown SQS redrive option.")
        for key in ("SourceQueueUrl", "DestinationQueueUrl"):
            if not isinstance(config.get(key), str) or not config[key]:
                raise WorkflowValidationError("Redrive requires source and destination queue URLs.")
        if config["SourceQueueUrl"] == config["DestinationQueueUrl"]:
            raise WorkflowValidationError("Redrive source and destination must differ.")
        limit = config.get("MaxMessages", 3)
        if type(limit) is not int or not 1 <= limit <= 10:
            raise WorkflowValidationError("Redrive must request between 1 and 10 messages.")

    def affected_records(self, config: dict[str, Any]) -> int:
        self.validate(config)
        return int(config.get("MaxMessages", 3))

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        self.validate(config)
        return {
            "simulation": True,
            "native_dry_run": False,
            "parameters": config,
            "note": "No messages received, sent or deleted; partial effects require reconciliation.",
        }

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        from flowops.providers.aws.backend import resource_scope

        self.validate(config)
        # Validate BOTH destinations before the first receive changes visibility.
        resource_scope(
            [{"QueueUrl": config[key]} for key in ("SourceQueueUrl", "DestinationQueueUrl")],
            context.aws,
            queue_endpoint=getattr(self.backend, "queue_endpoint", None),
        )
        received = self.actions["receive_message"].execute(
            {
                "QueueUrl": config["SourceQueueUrl"],
                "MaxNumberOfMessages": config.get("MaxMessages", 3),
                "VisibilityTimeout": 60,
                "MessageSystemAttributeNames": ["MessageGroupId"],
            },
            context,
        )
        messages = received.get("Messages", [])
        sent: list[str] = []
        deleted = 0
        stage = "send"
        try:
            for message in messages:
                parameters = {
                    "QueueUrl": config["DestinationQueueUrl"],
                    "MessageBody": message["Body"],
                }
                if urlparse(config["DestinationQueueUrl"]).path.endswith(".fifo"):
                    parameters.update(
                        MessageGroupId=message.get("Attributes", {}).get(
                            "MessageGroupId", "flowops-redrive"
                        ),
                        MessageDeduplicationId=message["MessageId"],
                    )
                self.actions["send_message"].execute(parameters, context)
                sent.append(message["MessageId"])
            stage = "delete"
            for message in messages:
                self.actions["delete_message"].execute(
                    {
                        "QueueUrl": config["SourceQueueUrl"],
                        "ReceiptHandle": message["ReceiptHandle"],
                    },
                    context,
                )
                deleted += 1
        except ProviderError as cause:
            error = ProviderError("RedrivePartialFailure", ambiguous=True)
            error.details = {
                "stage": stage,
                "sent_message_ids": sent,
                "deleted": deleted,
                "cause": cause.code,
            }
            raise error from cause
        return {
            "received": len(messages),
            "sent": len(sent),
            "deleted": deleted,
            "message_ids": sent,
        }
