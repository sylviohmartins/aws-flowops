"""Curated risk metadata over real botocore service models; unknown operations fail closed."""

from dataclasses import dataclass
from typing import Any

from flowops.domain.errors import PolicyViolation, WorkflowValidationError
from flowops.domain.models import Risk


@dataclass(frozen=True)
class Spec:
    service: str
    operation: str
    read_only: bool
    risk: Risk
    idempotent: bool = False

    @property
    def id(self) -> str:
        return f"{self.service}.{self.operation}"


READS = {
    "dynamodb": "list_tables describe_table get_item batch_get_item query scan transact_get_items",
    "sqs": "list_queues get_queue_attributes list_dead_letter_source_queues list_message_move_tasks",
    "sns": "list_topics list_subscriptions list_subscriptions_by_topic get_topic_attributes",
    "lambda": "list_functions get_function get_function_configuration list_versions_by_function list_aliases get_alias list_layers list_layer_versions get_layer_version",
    "s3": "list_buckets list_objects_v2 get_object head_object head_bucket",
}
WRITES = {
    "dynamodb": "put_item update_item delete_item batch_write_item transact_write_items execute_statement batch_execute_statement execute_transaction",
    "sqs": "send_message send_message_batch receive_message delete_message delete_message_batch change_message_visibility change_message_visibility_batch purge_queue start_message_move_task cancel_message_move_task",
    "sns": "create_topic publish publish_batch subscribe unsubscribe set_topic_attributes",
    "lambda": "invoke update_function_configuration update_function_code publish_version create_alias update_alias delete_alias publish_layer_version delete_layer_version",
    "s3": "put_object delete_object delete_objects copy_object",
}
CRITICAL = {
    "sqs.purge_queue",
    "sqs.start_message_move_task",
    "dynamodb.batch_write_item",
    "lambda.update_function_code",
    "lambda.delete_layer_version",
    "s3.delete_objects",
}
CURATED = [
    Spec(service, operation, True, Risk.READ_ONLY, True)
    for service, operations in READS.items()
    for operation in operations.split()
] + [
    Spec(
        service,
        operation,
        False,
        Risk.CRITICAL if f"{service}.{operation}" in CRITICAL else Risk.HIGH,
    )
    for service, operations in WRITES.items()
    for operation in operations.split()
]
SPECS = {spec.id: spec for spec in CURATED}
# These categories can expose credentials or alter the authority of the worker itself.
BLOCKED_SERVICES = {
    "iam",
    "sts",
    "organizations",
    "account",
    "secretsmanager",
    "sso",
    "sso-admin",
    "sso-oidc",
}

IAM_OVERRIDES = {
    "lambda.invoke": ("lambda:InvokeFunction",),
    "s3.list_buckets": ("s3:ListAllMyBuckets",),
    "s3.list_objects_v2": ("s3:ListBucket",),
    "s3.head_bucket": ("s3:ListBucket",),
    "s3.head_object": ("s3:GetObject",),
    "s3.copy_object": ("s3:GetObject", "s3:PutObject"),
    "s3.delete_objects": ("s3:DeleteObject",),
    "sqs.send_message_batch": ("sqs:SendMessage",),
    "sqs.delete_message_batch": ("sqs:DeleteMessage",),
    "sqs.change_message_visibility_batch": ("sqs:ChangeMessageVisibility",),
    "sqs.start_message_move_task": (
        "sqs:StartMessageMoveTask",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:SendMessage",
    ),
    "dynamodb.execute_statement": (
        "dynamodb:PartiQLSelect",
        "dynamodb:PartiQLInsert",
        "dynamodb:PartiQLUpdate",
        "dynamodb:PartiQLDelete",
    ),
    "dynamodb.batch_execute_statement": (
        "dynamodb:PartiQLSelect",
        "dynamodb:PartiQLInsert",
        "dynamodb:PartiQLUpdate",
        "dynamodb:PartiQLDelete",
    ),
    "dynamodb.execute_transaction": (
        "dynamodb:PartiQLSelect",
        "dynamodb:PartiQLInsert",
        "dynamodb:PartiQLUpdate",
        "dynamodb:PartiQLDelete",
    ),
}


class ModelCatalog:
    def __init__(self) -> None:
        import botocore.session

        self.session = botocore.session.get_session()

    def services(self) -> list[str]:
        return list(self.session.get_available_services())

    def operations(self, service: str) -> dict[str, str]:
        from botocore import xform_name

        if service not in self.services():
            raise WorkflowValidationError("Unknown AWS service.")
        model = self.session.get_service_model(service)
        return {xform_name(name): name for name in model.operation_names}

    def operation(self, service: str, operation: str) -> Any:
        mapping = self.operations(service)
        if operation not in mapping:
            raise WorkflowValidationError("Unknown AWS operation.")
        return self.session.get_service_model(service).operation_model(mapping[operation])

    def schema(self, shape: Any, depth: int = 0) -> dict[str, Any]:
        if shape is None:
            return {"type": "object", "properties": {}}
        names = {
            "structure": "object",
            "map": "object",
            "list": "array",
            "long": "integer",
            "double": "number",
            "float": "number",
            "timestamp": "string",
            "blob": "string",
        }
        schema: dict[str, Any] = {
            "type": names.get(shape.type_name, shape.type_name),
            "description": shape.documentation or "",
        }
        if shape.type_name == "blob":
            schema["contentEncoding"] = "base64"
        if depth >= 5:
            return schema
        if shape.type_name == "structure":
            schema.update(
                properties={
                    name: self.schema(member, depth + 1) for name, member in shape.members.items()
                },
                required=list(shape.required_members),
            )
        elif shape.type_name == "list":
            schema["items"] = self.schema(shape.member, depth + 1)
        elif shape.type_name == "map":
            schema["additionalProperties"] = self.schema(shape.value, depth + 1)
        if getattr(shape, "enum", None):
            schema["enum"] = shape.enum
        return schema

    def validate(self, service: str, operation: str, parameters: dict[str, Any]) -> None:
        from botocore.exceptions import ParamValidationError
        from botocore.validate import validate_parameters

        model = self.operation(service, operation)
        try:
            if model.input_shape:
                validate_parameters(parameters, model.input_shape)
            elif parameters:
                raise WorkflowValidationError("This AWS operation takes no parameters.")
        except ParamValidationError as exc:
            # Botocore reports may echo values, so expose only paths/types in schema UI.
            raise WorkflowValidationError(
                "Parameters do not match the AWS operation schema."
            ) from exc

    def generic_spec(self, service: str, operation: str, allowlist: set[str]) -> Spec:
        key = f"{service}.{operation}"
        if service in BLOCKED_SERVICES or key not in allowlist:
            raise PolicyViolation("Generic AWS operation is not enabled by the host allowlist.")
        self.operation(service, operation)
        return SPECS.get(key, Spec(service, operation, False, Risk.CRITICAL, False))
