from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.domain.errors import (
    AuthorizationError,
    PolicyViolation,
    ProviderError,
    WorkflowValidationError,
)
from flowops.domain.models import AWSContext, Identity, Risk
from flowops.providers.aws.actions import AWSAction, Limits, build_registry, register_generic
from flowops.providers.aws.catalog import CURATED, ModelCatalog, Spec
from flowops.providers.aws.resources import explore


class Backend:
    def __init__(self, result: Any = None) -> None:
        self.result = {} if result is None else result
        self.calls: list[tuple[str, str, dict[str, Any], Limits]] = []
        self.previews: list[tuple[str, str, dict[str, Any], Limits]] = []

    def invoke(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any:
        self.calls.append((service, operation, parameters, limits))
        return self.result

    def preview(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any:
        self.previews.append((service, operation, parameters, limits))
        return {"previewed": True}


def ctx(**correlation: str) -> ActionContext:
    return ActionContext(
        "run-1",
        "node-1",
        AWSContext(mode="demo"),
        True,
        correlation_context=correlation,
    )


def spec(
    service: str = "sqs",
    operation: str = "send_message",
    *,
    read_only: bool = False,
) -> Spec:
    return Spec(service, operation, read_only, Risk.READ_ONLY if read_only else Risk.HIGH)


def test_prepare_validates_controls_serializes_payloads_binary_and_limits() -> None:
    action = AWSAction(spec(), Backend())
    parameters, limits = action.prepare(
        {
            "QueueUrl": "q",
            "MessageBody": {"payment": 1},
            "binary": {"base64": "aGk="},
            "_flowops": {"max_items": 2, "max_pages": 1, "max_bytes": 2048},
        }
    )
    assert parameters["MessageBody"] == '{"payment":1}'
    assert parameters["binary"] == b"hi"
    assert limits.max_items == 2

    invalid_controls = [
        {"_flowops": "bad"},
        {"_flowops": {"unknown": 1}},
    ]
    for config in invalid_controls:
        with pytest.raises(WorkflowValidationError, match="Invalid FlowOps pagination"):
            action.prepare(config)

    invalid_limits = [
        {"max_items": True},
        {"max_items": 0},
        {"max_pages": 11},
        {"max_bytes": 100},
        {"paginate": 1},
    ]
    for controls in invalid_limits:
        with pytest.raises(PolicyViolation, match="exceeds configured"):
            action.prepare({"_flowops": controls})

    with pytest.raises(PolicyViolation, match="read-only"):
        action.prepare({"_flowops": {"paginate": True}})
    with pytest.raises(WorkflowValidationError, match="Invalid base64"):
        action.prepare({"binary": {"base64": "%%%"}})


def test_prepare_batch_and_dynamodb_bounded_reads() -> None:
    batch = AWSAction(spec(operation="send_message_batch"), Backend())
    parameters, _ = batch.prepare(
        {
            "Entries": [
                {"Id": "1", "MessageBody": {"x": 1}},
                {"Id": "2", "MessageBody": "already"},
            ]
        }
    )
    assert parameters["Entries"][0]["MessageBody"] == '{"x": 1}'
    assert parameters["Entries"][1]["MessageBody"] == "already"

    scan = AWSAction(spec("dynamodb", "scan", read_only=True), Backend())
    parameters, _ = scan.prepare({"_flowops": {"max_items": 10}})
    assert parameters["Limit"] == 10
    assert scan.prepare({"Limit": 2})[0]["Limit"] == 2
    for bad in (True, 0, 11):
        with pytest.raises(PolicyViolation, match="bounded Limit"):
            scan.prepare({"Limit": bad, "_flowops": {"max_items": 10}})


def test_correlation_attributes_cover_sqs_batch_sns_and_non_message_services() -> None:
    correlation = {f"key {index}": f"v{index}" for index in range(12)}
    context = ctx(**correlation)

    sqs = AWSAction(spec(), Backend())
    result = sqs._with_correlation(
        {"MessageAttributes": {"FlowOpsExecutionId": {"StringValue": "caller"}}}, context
    )
    assert result["MessageAttributes"]["FlowOpsExecutionId"]["StringValue"] == "caller"
    assert len(result["MessageAttributes"]) == 11
    assert "FlowOps_key_0" in result["MessageAttributes"]

    batch = AWSAction(spec(operation="send_message_batch"), Backend())
    batch_result = batch._with_correlation(
        {
            "Entries": [
                {"Id": "1"},
                {"Id": "2", "MessageAttributes": "invalid"},
                "invalid",
            ]
        },
        context,
    )
    assert (
        batch_result["Entries"][0]["MessageAttributes"]["FlowOpsExecutionId"]["StringValue"]
        == "run-1"
    )
    assert batch_result["Entries"][1]["MessageAttributes"] == "invalid"

    sns = AWSAction(spec("sns", "publish"), Backend())
    sns_result = sns._with_correlation({}, context)
    assert sns_result["MessageAttributes"]["FlowOpsExecutionId"]["StringValue"] == "run-1"

    dynamo = AWSAction(spec("dynamodb", "put_item"), Backend())
    original = {"Item": {"id": {"S": "1"}}}
    assert dynamo._with_correlation(original, context) is original
    assert AWSAction._attribute_name("!!!") == "___"
    assert AWSAction._attribute_name("") == "Context"


def test_validate_preview_execute_and_partial_failure_paths() -> None:
    class Catalog:
        def __init__(self) -> None:
            self.validated: list[tuple[str, str, dict[str, Any]]] = []

        def operation(self, service: str, operation: str) -> Any:
            return SimpleNamespace(name="SendMessage", input_shape=None, output_shape=None)

        def schema(self, shape: Any) -> dict[str, Any]:
            return {"type": "object"}

        def validate(self, service: str, operation: str, parameters: dict[str, Any]) -> None:
            self.validated.append((service, operation, parameters))

    catalog = Catalog()
    backend = Backend({"MessageId": "1"})
    action = AWSAction(spec(), backend, catalog)  # type: ignore[arg-type]
    action.validate({"MessageBody": "x"})
    assert catalog.validated[0][0:2] == ("sqs", "send_message")

    preview = action.preview({"MessageBody": "x"}, ctx(trace="abc"))
    assert preview["simulation"] is True
    assert preview["simulated_result"] == {"previewed": True}
    assert backend.previews
    assert action.execute({"MessageBody": "x"}, ctx()) == {"MessageId": "1"}

    class InvokeOnly:
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            return {}

    no_preview = AWSAction(spec(), InvokeOnly())  # type: ignore[arg-type]
    assert no_preview.preview({}, ctx())["simulated_result"] is None

    partial_results = [
        {"UnprocessedItems": {"t": [{}]}},
        {"UnprocessedKeys": {"t": [{}]}},
        {"Failed": [{"Code": "x"}]},
        {"FunctionError": "Unhandled"},
        {"Responses": [{"Error": {"Code": "x"}}]},
    ]
    for result in partial_results:
        failing = AWSAction(spec(), Backend(result))
        with pytest.raises(ProviderError) as error:
            failing.execute({}, ctx())
        assert error.value.code == "PartialFailure"
        assert error.value.ambiguous is True
        assert error.value.details == result


def test_build_registry_register_generic_and_duplicate_registration() -> None:
    backend = Backend()
    registry = build_registry(backend)
    assert len(registry.list()) == len(CURATED)

    class Catalog:
        def generic_spec(self, service: str, operation: str, allowlist: set[str]) -> Spec:
            assert f"{service}.{operation}" in allowlist
            return Spec(service, operation, False, Risk.CRITICAL)

        def operation(self, service: str, operation: str) -> Any:
            return SimpleNamespace(name="Custom", input_shape=None, output_shape=None)

        def schema(self, shape: Any) -> dict[str, Any]:
            return {"type": "object"}

    catalog = Catalog()
    action_id = register_generic(
        registry,
        catalog,  # type: ignore[arg-type]
        backend,
        "s3",
        "custom_operation",
        {"s3.custom_operation"},
    )
    assert action_id == "s3.custom_operation"
    size = len(registry.list())
    assert (
        register_generic(
            registry,
            catalog,  # type: ignore[arg-type]
            backend,
            "s3",
            "custom_operation",
            {"s3.custom_operation"},
        )
        == action_id
    )
    assert len(registry.list()) == size


def test_catalog_services_operations_schema_validation_and_generic_policy() -> None:
    class Shape:
        def __init__(
            self,
            type_name: str,
            *,
            documentation: str = "",
            members: dict[str, Any] | None = None,
            required_members: list[str] | None = None,
            member: Any = None,
            value: Any = None,
            enum: list[str] | None = None,
        ) -> None:
            self.type_name = type_name
            self.documentation = documentation
            self.members = members or {}
            self.required_members = required_members or []
            self.member = member
            self.value = value
            self.enum = enum

    string = Shape("string", documentation="name", enum=["a", "b"])
    structure = Shape("structure", members={"Name": string}, required_members=["Name"])
    list_shape = Shape("list", member=string)
    map_shape = Shape("map", value=string)
    operation_model = SimpleNamespace(name="GetThing", input_shape=None, output_shape=structure)
    service_model = SimpleNamespace(
        operation_names=["GetThing"],
        operation_model=lambda name: operation_model,
    )
    session = SimpleNamespace(
        get_available_services=lambda: ["fake"],
        get_service_model=lambda service: service_model,
    )
    catalog = ModelCatalog.__new__(ModelCatalog)
    catalog.session = session

    assert catalog.services() == ["fake"]
    assert catalog.operations("fake") == {"get_thing": "GetThing"}
    assert catalog.operation("fake", "get_thing") is operation_model
    with pytest.raises(WorkflowValidationError, match="Unknown AWS service"):
        catalog.operations("missing")
    with pytest.raises(WorkflowValidationError, match="Unknown AWS operation"):
        catalog.operation("fake", "missing")

    assert catalog.schema(None) == {"type": "object", "properties": {}}
    assert catalog.schema(Shape("blob"))["contentEncoding"] == "base64"
    assert catalog.schema(structure)["required"] == ["Name"]
    assert catalog.schema(list_shape)["items"]["enum"] == ["a", "b"]
    assert catalog.schema(map_shape)["additionalProperties"]["type"] == "string"
    assert "properties" not in catalog.schema(structure, depth=5)

    catalog.validate("fake", "get_thing", {})
    with pytest.raises(WorkflowValidationError, match="takes no parameters"):
        catalog.validate("fake", "get_thing", {"x": 1})

    with pytest.raises(PolicyViolation, match="allowlist"):
        catalog.generic_spec("iam", "anything", {"iam.anything"})
    with pytest.raises(PolicyViolation, match="allowlist"):
        catalog.generic_spec("fake", "get_thing", set())
    generic = catalog.generic_spec("fake", "get_thing", {"fake.get_thing"})
    assert generic.risk == Risk.CRITICAL
    assert generic.read_only is False


def test_resource_explorer_uses_same_authorization_and_action_boundary() -> None:
    class ReadAction:
        metadata = Metadata("s3.list_buckets", "aws", "s3", "list_buckets", "list")

        def validate(self, config: dict[str, Any]) -> None:
            return None

        def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
            return {}

        def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
            assert context.node_id == "resource_explorer"
            assert context.dry_run is True
            return {"Buckets": [{"Name": "one"}]}

    registry = ActionRegistry()
    registry.register(ReadAction())
    viewer = Identity(id="viewer", permissions={"aws.read"})
    result = explore(registry, viewer, AWSContext(), "s3")
    assert result["Buckets"][0]["Name"] == "one"

    with pytest.raises(AuthorizationError):
        explore(registry, Identity(id="none"), AWSContext(), "s3")
    with pytest.raises(KeyError):
        explore(registry, viewer, AWSContext(), "unknown")
