from typing import Any

from flowops.core.actions import ActionContext
from flowops.domain.models import AWSContext
from flowops.providers.aws.actions import AWSAction, Limits
from flowops.providers.aws.catalog import SPECS


class CaptureBackend:
    def __init__(self) -> None:
        self.parameters: dict[str, Any] = {}

    def invoke(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any:
        self.parameters = parameters
        return {"MessageId": "message-1"}


def test_sqs_message_attributes_receive_flowops_correlation() -> None:
    backend = CaptureBackend()
    action = AWSAction(SPECS["sqs.send_message"], backend)
    context = ActionContext(
        "exec-123",
        "send",
        AWSContext(),
        False,
        {"incident": "INC-42"},
    )
    action.execute(
        {
            "QueueUrl": "https://sqs.sa-east-1.amazonaws.com/000000000000/demo",
            "MessageBody": "payload",
            "MessageAttributes": {"Existing": {"DataType": "String", "StringValue": "kept"}},
        },
        context,
    )
    attributes = backend.parameters["MessageAttributes"]
    assert attributes["FlowOpsExecutionId"]["StringValue"] == "exec-123"
    assert attributes["FlowOps_incident"]["StringValue"] == "INC-42"
    assert attributes["Existing"]["StringValue"] == "kept"
