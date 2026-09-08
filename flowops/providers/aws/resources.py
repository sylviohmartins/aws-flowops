"""Explicit, bounded reads through the same authorization/provider boundary."""

from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry
from flowops.core.expressions import references
from flowops.core.policies import require
from flowops.core.security import bounded_output
from flowops.domain.errors import PolicyViolation, WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, new_id

EXPLORERS = {
    "dynamodb": ("dynamodb.list_tables", "TableNames"),
    "sqs": ("sqs.list_queues", "QueueUrls"),
    "sns": ("sns.list_topics", "Topics"),
    "lambda": ("lambda.list_functions", "Functions"),
    "s3": ("s3.list_buckets", "Buckets"),
}


def read_action(
    registry: ActionRegistry,
    user: Identity,
    context: AWSContext,
    action_id: str,
    config: dict[str, Any],
) -> Any:
    """Execute one explicit read action, never a mutation or a mapped request."""
    require(user, "aws.read")
    action = registry.get(action_id)
    if not action.metadata.read_only:
        raise PolicyViolation("Resource preview accepts read-only actions only.")
    if references(config):
        raise WorkflowValidationError(
            "Read preview requires literal inputs; mappings run only during execution."
        )
    action.validate(config)
    execution_id = new_id()
    try:
        result = action.execute(
            config, ActionContext(execution_id, "resource_explorer", context, True)
        )
        return bounded_output(result)
    finally:
        backend = getattr(action, "backend", None)
        release = getattr(backend, "release", None)
        if callable(release):
            release(execution_id)


def explore(registry: ActionRegistry, user: Identity, context: AWSContext, service: str) -> Any:
    action_id, _ = EXPLORERS[service]
    return read_action(
        registry,
        user,
        context,
        action_id,
        {"_flowops": {"paginate": True, "max_items": 100, "max_pages": 3}},
    )


def resource_choices(service: str, result: Any) -> list[str]:
    """Extract safe selectable identifiers from a bounded list response."""
    if not isinstance(result, dict) or service not in EXPLORERS:
        return []
    entries = result.get(EXPLORERS[service][1], [])
    item_name = {"sns": "TopicArn", "lambda": "FunctionName", "s3": "Name"}.get(service)
    choices: set[str] = set()
    if not isinstance(entries, list):
        return []
    for entry in entries:
        value = entry.get(item_name) if item_name and isinstance(entry, dict) else entry
        if isinstance(value, str):
            choices.add(value)
    return sorted(choices)
