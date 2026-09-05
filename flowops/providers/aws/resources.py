"""Read-only resource discovery through the same authorization/provider boundary."""

from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry
from flowops.core.policies import require
from flowops.domain.models import AWSContext, Identity, new_id

EXPLORERS = {
    "dynamodb": ("dynamodb.list_tables", "TableNames"),
    "sqs": ("sqs.list_queues", "QueueUrls"),
    "sns": ("sns.list_topics", "Topics"),
    "lambda": ("lambda.list_functions", "Functions"),
    "s3": ("s3.list_buckets", "Buckets"),
}


def explore(registry: ActionRegistry, user: Identity, context: AWSContext, service: str) -> Any:
    require(user, "aws.read")
    action_id, _ = EXPLORERS[service]
    return registry.get(action_id).execute(
        {}, ActionContext(new_id(), "resource_explorer", context, True)
    )
