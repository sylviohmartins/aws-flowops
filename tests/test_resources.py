from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.domain.errors import PolicyViolation, WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Risk
from flowops.providers.aws.catalog import CURATED, READS, ModelCatalog
from flowops.providers.aws.resources import (
    DISCOVERY_RULES,
    INSPECTION_RULES,
    DiscoveryRule,
    InspectionRule,
    discover_field,
    discovery_choices,
    discovery_request,
    discovery_rules,
    discovery_services,
    dynamodb_observed_fields,
    explore,
    inspect_resource,
    inspection_request,
    inspection_rules,
    missing_dependencies,
    read_action,
    resource_choices,
    sample_dynamodb_fields,
    supporting_discovery_rules,
)


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


def test_dynamodb_observed_fields_are_explicitly_sampled_not_schema() -> None:
    result = {
        "Items": [
            {"paymentId": {"S": "1"}, "amount": {"N": "10"}, "status": {"S": "OK"}},
            {"paymentId": {"S": "2"}, "amount": {"N": "20"}, "metadata": {"M": {}}},
            "ignored",
        ]
    }
    assert dynamodb_observed_fields(result) == [
        {"field": "amount", "types": "N", "observed": 2},
        {"field": "metadata", "types": "M", "observed": 1},
        {"field": "paymentId", "types": "S", "observed": 2},
        {"field": "status", "types": "S", "observed": 1},
    ]
    action = FakeAction("dynamodb.scan", read_only=True, result=result)
    rows, sampled = sample_dynamodb_fields(
        registry(action), identity(), AWSContext(), "payments", limit=10
    )
    assert rows == dynamodb_observed_fields(result)
    assert sampled == 3
    assert action.validated == [{"TableName": "payments", "Limit": 10}]
    assert action.contexts[0].dry_run is True

    with pytest.raises(WorkflowValidationError, match="literal table name"):
        sample_dynamodb_fields(registry(action), identity(), AWSContext(), "")
    with pytest.raises(WorkflowValidationError, match="between 1 and 25"):
        sample_dynamodb_fields(registry(action), identity(), AWSContext(), "payments", limit=26)


def test_explore_adds_safe_pagination_and_choices() -> None:
    assert discovery_services() == sorted(READS)
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


def test_discovery_rules_follow_action_schema_and_explicit_action_scope() -> None:
    schema = {
        "type": "object",
        "properties": {"FunctionName": {"type": "string"}, "Qualifier": {"type": "string"}},
    }
    rules = discovery_rules("lambda.invoke", schema)
    assert [rule.field for rule in rules] == ["FunctionName", "Qualifier"]
    assert discovery_rules("lambda.publish_version", schema)[0].field == "FunctionName"
    assert all(
        rule.field != "Qualifier" for rule in discovery_rules("lambda.publish_version", schema)
    )

    s3 = discovery_rules(
        "s3.delete_object",
        {"type": "object", "properties": {"Bucket": {}, "Key": {}}},
    )
    assert [rule.field for rule in s3] == ["Bucket", "Key"]
    assert all(
        rule.field != "Key"
        for rule in discovery_rules("s3.put_object", {"properties": {"Key": {}}})
    )

    step_schema = {"properties": {"executionArn": {"type": "string"}}}
    step_rules = discovery_rules("stepfunctions.stop_execution", step_schema)
    assert [rule.field for rule in step_rules] == ["executionArn"]
    assert [
        rule.field
        for rule in supporting_discovery_rules("stepfunctions.stop_execution", step_schema)
    ] == ["stateMachineArn"]

    elb_schema = {"properties": {"ListenerArn": {}, "RuleArns": {}}}
    assert [
        rule.field for rule in supporting_discovery_rules("elbv2.describe_rules", elb_schema)
    ] == ["LoadBalancerArn"]

    move_schema = {"properties": {"SourceArn": {}, "DestinationArn": {}}}
    assert [rule.field for rule in discovery_rules("sqs.start_message_move_task", move_schema)] == [
        "SourceArn",
        "DestinationArn",
    ]
    assert [
        rule.field
        for rule in supporting_discovery_rules("sqs.start_message_move_task", move_schema)
    ] == ["SourceQueueUrl", "DestinationQueueUrl"]

    cancel_schema = {"properties": {"TaskHandle": {}}}
    assert [
        rule.field for rule in discovery_rules("sqs.cancel_message_move_task", cancel_schema)
    ] == ["TaskHandle"]
    assert [
        rule.field
        for rule in supporting_discovery_rules("sqs.cancel_message_move_task", cancel_schema)
    ] == ["SourceQueueUrl", "SourceQueueArn"]

    lambda_code_schema = {
        "properties": {
            "FunctionName": {},
            "S3Bucket": {},
            "S3Key": {},
        }
    }
    assert [
        rule.field for rule in discovery_rules("lambda.update_function_code", lambda_code_schema)
    ] == ["FunctionName", "S3Bucket", "S3Key"]

    event_schema = {"properties": {"Entries": {}, "EndpointId": {}}}
    assert [rule.field for rule in discovery_rules("events.put_events", event_schema)] == [
        "EndpointId"
    ]


def test_discovery_extracts_nested_values_and_builds_bounded_dependent_request() -> None:
    instance_rule = next(rule for rule in DISCOVERY_RULES if rule.field == "InstanceIds")
    result = {
        "Reservations": [
            {"Instances": [{"InstanceId": "i-2"}, {"InstanceId": "i-1"}]},
            {"Instances": [{"InstanceId": "i-1"}]},
        ]
    }
    assert discovery_choices(instance_rule, result) == ["i-1", "i-2"]

    object_rule = next(
        rule
        for rule in DISCOVERY_RULES
        if rule.action_id == "s3.list_objects_v2" and rule.field == "Key"
    )
    request = discovery_request(object_rule, {"Bucket": "operations"})
    assert request["Bucket"] == "operations"
    assert request["_flowops"] == {"paginate": True, "max_items": 100, "max_pages": 3}
    with pytest.raises(WorkflowValidationError, match="Bucket"):
        discovery_request(object_rule, {"Bucket": "{{ params.bucket }}"})

    source_arn = next(
        rule
        for rule in DISCOVERY_RULES
        if rule.field == "SourceArn" and "sqs.start_message_move_task" in rule.actions
    )
    assert discovery_request(source_arn, {"SourceQueueUrl": "https://sqs.local/source"}) == {
        "QueueUrl": "https://sqs.local/source",
        "AttributeNames": ["QueueArn"],
    }


def test_discover_field_uses_only_declared_read_action_and_respects_no_paginator() -> None:
    rule = next(rule for rule in DISCOVERY_RULES if rule.action_id == "events.list_event_buses")
    action = FakeAction(
        "events.list_event_buses",
        read_only=True,
        result={"EventBuses": [{"Name": "default"}, {"Name": "payments"}]},
    )
    choices = discover_field(registry(action), identity(), AWSContext(), rule, {})
    assert choices == ["default", "payments"]
    assert action.validated == [{}]
    assert action.contexts[0].dry_run is True


def test_ec2_image_discovery_is_scoped_to_owned_amis_and_inspectable() -> None:
    rules = discovery_rules(
        "ec2.describe_images",
        {"type": "object", "properties": {"ImageIds": {"type": "array"}}},
    )
    image_rule = next(rule for rule in rules if rule.field == "ImageIds")
    assert discovery_request(image_rule, {}) == {"Owners": ["self"]}
    assert discovery_choices(
        image_rule,
        {"Images": [{"ImageId": "ami-2"}, {"ImageId": "ami-1"}]},
    ) == ["ami-1", "ami-2"]

    inspectors = inspection_rules(
        "ec2.describe_images",
        {"type": "object", "properties": {"ImageIds": {"type": "array"}}},
    )
    image_inspector = next(rule for rule in inspectors if rule.field == "ImageIds")
    assert inspection_request(image_inspector, {}, ["ami-1"]) == {"ImageIds": ["ami-1"]}


def test_discovery_supports_multiple_response_paths_and_cloudwatch() -> None:
    index_rule = next(rule for rule in DISCOVERY_RULES if rule.field == "IndexName")
    indexes = discovery_choices(
        index_rule,
        {
            "Table": {
                "GlobalSecondaryIndexes": [{"IndexName": "gsi-status"}],
                "LocalSecondaryIndexes": [{"IndexName": "lsi-created"}],
            }
        },
    )
    assert indexes == ["gsi-status", "lsi-created"]

    alarm_rule = next(rule for rule in DISCOVERY_RULES if rule.field == "AlarmNames")
    alarms = discovery_choices(
        alarm_rule,
        {
            "MetricAlarms": [{"AlarmName": "cpu-high"}],
            "CompositeAlarms": [{"AlarmName": "service-unhealthy"}],
        },
    )
    assert alarms == ["cpu-high", "service-unhealthy"]


def test_inspection_request_is_literal_bounded_and_read_only() -> None:
    sqs_rule = next(rule for rule in INSPECTION_RULES if rule.field == "QueueUrl")
    assert inspection_request(sqs_rule, {}, "https://sqs.local/queue") == {
        "QueueUrl": "https://sqs.local/queue",
        "AttributeNames": ["All"],
    }

    qualifier_rule = next(rule for rule in INSPECTION_RULES if rule.field == "Qualifier")
    with pytest.raises(WorkflowValidationError, match="FunctionName"):
        inspection_request(
            qualifier_rule,
            {"FunctionName": "{{ params.function_name }}"},
            "live",
        )

    action = FakeAction(
        "sqs.get_queue_attributes",
        read_only=True,
        result={"Attributes": {"QueueArn": "arn:aws:sqs:::queue"}},
    )
    output = inspect_resource(
        registry(action),
        identity(),
        AWSContext(),
        sqs_rule,
        {},
        "https://sqs.local/queue",
    )
    assert output["Attributes"]["QueueArn"].endswith("queue")
    assert action.validated[0]["AttributeNames"] == ["All"]
    assert action.contexts[0].dry_run is True
    assert len(action.backend.released) == 1


def test_discovery_and_inspection_rules_match_curated_botocore_models() -> None:
    catalog = ModelCatalog()
    specs = {spec.id: spec for spec in CURATED}

    for rule in (*DISCOVERY_RULES, *INSPECTION_RULES):
        assert rule.action_id in specs
        assert specs[rule.action_id].read_only is True
        if isinstance(rule, DiscoveryRule) and rule.auxiliary:
            continue
        targets = (
            [spec for spec in CURATED if spec.id in rule.actions]
            if rule.actions
            else [spec for spec in CURATED if spec.service == rule.service]
        )
        applicable = []
        for spec in targets:
            model = catalog.operation(spec.service, spec.operation)
            fields = set(model.input_shape.members) if model.input_shape else set()
            if rule.field in fields:
                applicable.append(fields)
        assert applicable, (rule.service, rule.field, rule.action_id)

    schema = {"properties": {"QueueUrl": {}, "MessageBody": {}}}
    assert [rule.field for rule in inspection_rules("sqs.send_message", schema)] == ["QueueUrl"]


def test_declared_resource_requests_validate_against_botocore_models() -> None:
    catalog = ModelCatalog()
    for rule in DISCOVERY_RULES:
        current = {source: "sample" for _, source in rule.request_from}
        request = discovery_request(rule, current)
        request.pop("_flowops", None)
        service, operation = rule.action_id.split(".", 1)
        catalog.validate(service, operation, request)

    for rule in INSPECTION_RULES:
        current = {source: "sample" for _, source, _ in rule.request_from if source != rule.field}
        request = inspection_request(rule, current, "sample")
        request.pop("_flowops", None)
        service, operation = rule.action_id.split(".", 1)
        catalog.validate(service, operation, request)


def test_discovery_and_inspection_edge_cases() -> None:
    assert discovery_rules("sqs.send_message", {"properties": []}) == []
    assert inspection_rules("sqs.send_message", {"properties": []}) == []
    with pytest.raises(KeyError):
        explore(ActionRegistry(), identity(), AWSContext(), "unknown")

    dependent = DiscoveryRule(
        "s3",
        "Key",
        "s3.list_objects_v2",
        ("Contents", "*", "Key"),
        request_from=(("Bucket", "Bucket"),),
    )
    assert missing_dependencies(dependent, {}) == ["Bucket"]
    assert missing_dependencies(dependent, {"Bucket": ""}) == ["Bucket"]
    assert missing_dependencies(dependent, {"Bucket": "{{ params.bucket }}"}) == ["Bucket"]
    assert missing_dependencies(dependent, {"Bucket": "ops"}) == []
    assert discovery_choices(
        dependent,
        {"Contents": [{"Key": "b"}, {"Key": ""}, {"Key": 3}, {"Other": "x"}]},
    ) == ["b"]

    inspection = InspectionRule(
        "fake",
        "Resource",
        "fake.describe",
        request_from=(
            ("Resources", "Resource", True),
            ("Scope", "Scope", False),
        ),
        constants=(("Mode", "full"),),
        paginate=True,
    )
    assert inspection_request(
        inspection,
        {"Scope": "regional"},
        ["one", "two"],
    ) == {
        "Resources": ["one", "two"],
        "Scope": "regional",
        "Mode": "full",
        "_flowops": {"paginate": True, "max_items": 100, "max_pages": 3},
    }
    with pytest.raises(WorkflowValidationError, match="Scope"):
        inspection_request(inspection, {"Scope": 3}, "one")
