"""Small provider extension contracts and metadata-driven discovery."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import AWSContext, Risk


@dataclass(frozen=True)
class Metadata:
    id: str
    provider: str
    service: str
    operation: str
    description: str
    risk: Risk = Risk.READ_ONLY
    read_only: bool = True
    idempotent: bool = True
    supports_preview: bool = True
    required_permissions: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionContext:
    execution_id: str
    node_id: str
    aws: AWSContext
    dry_run: bool
    correlation_context: dict[str, str] = field(default_factory=dict)


class Action(Protocol):
    metadata: Metadata

    def validate(self, config: dict[str, Any]) -> None: ...
    def preview(self, config: dict[str, Any], context: ActionContext) -> Any: ...
    def execute(self, config: dict[str, Any], context: ActionContext) -> Any: ...


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        if action.metadata.id in self._actions:
            raise WorkflowValidationError(f"Duplicate action: {action.metadata.id}")
        self._actions[action.metadata.id] = action

    def get(self, action_id: str) -> Action:
        if action_id not in self._actions:
            raise WorkflowValidationError(f"Unknown action: {action_id}")
        return self._actions[action_id]

    def list(self) -> list[Metadata]:
        return [self._actions[key].metadata for key in sorted(self._actions)]
