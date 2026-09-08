from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.domain.errors import PolicyViolation, WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Risk
from flowops.providers.aws.resources import explore, read_action, resource_choices


@dataclass
class FakeBackend:
    released: list[str]

    def release(self, execution_id: str) -> None:
        self.released.append(execution_id)


class FakeAction:
    def __init__(self, action_id: str, *, read_only: bool, result: Any) -> None:
        self.backend = FakeBackend([])
        self.metadata = Metadata(
            action_id,
            "aws",
            action_id.split(".")[0],
            action_id.split(".")[1],
            action_id,
            risk=Risk.READ_ONLY if read_only else Risk.HIGH,
            read_only=read_only,
        )
        self.result = result
        self.validated: list[dict[str, Any]] = []
        self.contexts: list[ActionContext] = []

    def validate(self, config: dict[str, Any]) -> None:
        self.validated.append(config)

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        self.contexts.append(context)
        return self.result


def registry(*actions: FakeAction) -> ActionRegistry:
    result = ActionRegistry()
    for action in actions:
        result.register(action)
    return result


def identity() -> Identity:
    return Identity(id="reader", roles=["ADMIN"], permissions=["aws.read"])


def test_read_action_is_explicit_read_only_and_releases_provider() -> None:
    action = FakeAction("dynamodb.list_tables", read_only=True, result={"TableNames": ["a"]})
    output = read_action(
        registry(action), identity(), AWSContext(), "dynamodb.list_tables", {"literal": "x"}
    )
    assert output == {"TableNames": ["a"]}
    assert action.validated == [{"literal": "x"}]
    assert action.contexts[0].dry_run is True
    assert len(action.backend.released) == 1

    with pytest.raises(WorkflowValidationError):
        read_action(
            registry(action),
            identity(),
            AWSContext(),
            action.metadata.id,
            {"x": "{{ params.x }}"},
        )

    mutation = FakeAction("dynamodb.put_item", read_only=False, result={})
    with pytest.raises(PolicyViolation):
        read_action(registry(mutation), identity(), AWSContext(), mutation.metadata.id, {})


def test_explore_adds_safe_pagination_and_choices() -> None:
    action = FakeAction("sqs.list_queues", read_only=True, result={"QueueUrls": ["q2", "q1"]})
    output = explore(registry(action), identity(), AWSContext(), "sqs")
    assert output["QueueUrls"] == ["q2", "q1"]
    assert action.validated[0]["_flowops"]["max_items"] == 100
    assert resource_choices("sqs", output) == ["q1", "q2"]
    assert resource_choices("sns", {"Topics": [{"TopicArn": "arn:one"}]}) == ["arn:one"]
    assert resource_choices("lambda", {"Functions": [{"FunctionName": "fn"}]}) == ["fn"]
    assert resource_choices("s3", {"Buckets": [{"Name": "bucket"}]}) == ["bucket"]
    assert resource_choices("dynamodb", {"TableNames": ["table"]}) == ["table"]
    assert resource_choices("sqs", {"QueueUrls": {"not": "a-list"}}) == []
    assert resource_choices("unknown", {}) == []
    assert resource_choices("s3", None) == []
