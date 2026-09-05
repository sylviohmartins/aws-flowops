"""Actions use schema validation and a narrow backend; every listed AWS call is real."""

import base64
import json
from dataclasses import dataclass
from typing import Any, Protocol

from flowops.core.actions import ActionContext, ActionRegistry, Metadata
from flowops.domain.errors import PolicyViolation, ProviderError, WorkflowValidationError
from flowops.providers.aws.catalog import CURATED, IAM_OVERRIDES, ModelCatalog, Spec


@dataclass(frozen=True)
class Limits:
    max_items: int = 100
    max_pages: int = 3
    max_bytes: int = 131072
    paginate: bool = False


class Backend(Protocol):
    def invoke(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any: ...


class AWSAction:
    def __init__(self, spec: Spec, backend: Backend, catalog: ModelCatalog | None = None):
        self.spec, self.backend, self.catalog = spec, backend, catalog
        model = catalog.operation(spec.service, spec.operation) if catalog else None
        operation_name = (
            model.name if model else "".join(part.title() for part in spec.operation.split("_"))
        )
        self.metadata = Metadata(
            spec.id,
            "aws",
            spec.service,
            spec.operation,
            f"AWS {spec.service} {operation_name}",
            risk=spec.risk,
            read_only=spec.read_only,
            idempotent=spec.idempotent,
            required_permissions=IAM_OVERRIDES.get(spec.id, (f"{spec.service}:{operation_name}",)),
            input_schema=catalog.schema(model.input_shape)
            if catalog and model
            else {"type": "object"},
            output_schema=catalog.schema(model.output_shape)
            if catalog and model
            else {"type": "object"},
        )

    def prepare(self, config: dict[str, Any]) -> tuple[dict[str, Any], Limits]:
        parameters = dict(config)
        control = parameters.pop("_flowops", {})
        if not isinstance(control, dict) or control.keys() - {
            "max_items",
            "max_pages",
            "max_bytes",
            "paginate",
        }:
            raise WorkflowValidationError("Invalid FlowOps pagination options.")
        limits = Limits(**control)
        if (
            type(limits.max_items) is not int
            or not 1 <= limits.max_items <= 1000
            or type(limits.max_pages) is not int
            or not 1 <= limits.max_pages <= 10
            or type(limits.max_bytes) is not int
            or not 1024 <= limits.max_bytes <= 1048576
            or type(limits.paginate) is not bool
        ):
            raise PolicyViolation("AWS request exceeds configured page/item/payload limits.")
        if limits.paginate and not self.spec.read_only:
            raise PolicyViolation("Automatic pagination is limited to curated read-only actions.")
        for key in ("MessageBody", "Message", "Payload"):
            if key in parameters and isinstance(parameters[key], (dict, list)):
                parameters[key] = json.dumps(
                    parameters[key], ensure_ascii=False, separators=(",", ":")
                )
        if self.spec.operation == "send_message_batch":
            parameters["Entries"] = [
                dict(entry)
                | {
                    "MessageBody": json.dumps(entry["MessageBody"], ensure_ascii=False)
                    if isinstance(entry.get("MessageBody"), (dict, list))
                    else entry.get("MessageBody")
                }
                for entry in parameters.get("Entries", [])
            ]

        def binary(value: Any) -> Any:
            if isinstance(value, dict):
                if set(value) == {"base64"}:
                    try:
                        return base64.b64decode(value["base64"], validate=True)
                    except (ValueError, TypeError) as exc:
                        raise WorkflowValidationError("Invalid base64 binary parameter.") from exc
                return {k: binary(v) for k, v in value.items()}
            if isinstance(value, list):
                return [binary(v) for v in value]
            return value

        parameters = binary(parameters)
        if self.spec.service == "dynamodb" and self.spec.operation in {"query", "scan"}:
            requested = parameters.get("Limit", limits.max_items)
            if type(requested) is not int or not 1 <= requested <= limits.max_items:
                raise PolicyViolation("DynamoDB reads require a bounded Limit.")
            parameters["Limit"] = requested
        return parameters, limits

    def validate(self, config: dict[str, Any]) -> None:
        parameters, _ = self.prepare(config)
        if self.catalog:
            self.catalog.validate(self.spec.service, self.spec.operation, parameters)

    def preview(self, config: dict[str, Any], context: ActionContext) -> Any:
        parameters, limits = self.prepare(config)
        result: Any = None
        simulator = getattr(self.backend, "preview", None)
        if callable(simulator):
            result = simulator(
                self.spec.service,
                self.spec.operation,
                parameters,
                context,
                limits,
            )
        return {
            "simulation": True,
            "native_dry_run": False,
            "action": self.spec.id,
            "parameters": config,
            "limits": {"max_items": limits.max_items, "max_pages": limits.max_pages},
            "simulated_result": result,
            "note": "Mutation was not called against the selected AWS account.",
        }

    def execute(self, config: dict[str, Any], context: ActionContext) -> Any:
        parameters, limits = self.prepare(config)
        result = self.backend.invoke(
            self.spec.service, self.spec.operation, parameters, context, limits
        )
        if isinstance(result, dict) and (
            result.get("UnprocessedItems")
            or result.get("UnprocessedKeys")
            or result.get("Failed")
            or result.get("FunctionError")
            or any(isinstance(r, dict) and r.get("Error") for r in result.get("Responses", []))
        ):
            error = ProviderError("PartialFailure", ambiguous=True)
            error.details = result
            raise error
        return result


def build_registry(backend: Backend, *, catalog: ModelCatalog | None = None) -> ActionRegistry:
    registry = ActionRegistry()
    for spec in CURATED:
        registry.register(AWSAction(spec, backend, catalog))
    return registry


def register_generic(
    registry: ActionRegistry,
    catalog: ModelCatalog,
    backend: Backend,
    service: str,
    operation: str,
    allowlist: set[str],
) -> str:
    spec = catalog.generic_spec(service, operation, allowlist)
    if spec.id not in {metadata.id for metadata in registry.list()}:
        registry.register(AWSAction(spec, backend, catalog))
    return spec.id
