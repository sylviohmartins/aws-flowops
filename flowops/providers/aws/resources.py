"""Explicit, bounded reads through the same authorization/provider boundary."""

from dataclasses import dataclass
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


@dataclass(frozen=True)
class DiscoveryRule:
    """One bounded read that can supply valid values for an AWS input field."""

    service: str
    field: str
    action_id: str
    result_path: tuple[str, ...]
    additional_result_paths: tuple[tuple[str, ...], ...] = ()
    request_from: tuple[tuple[str, str], ...] = ()
    constants: tuple[tuple[str, Any], ...] = ()
    actions: tuple[str, ...] = ()
    multiple: bool = False
    paginate: bool = True
    auxiliary: bool = False


def _rule(
    service: str,
    field: str,
    action_id: str,
    result_path: str,
    *,
    additional_result_paths: tuple[str, ...] = (),
    request_from: tuple[tuple[str, str], ...] = (),
    constants: tuple[tuple[str, Any], ...] = (),
    actions: tuple[str, ...] = (),
    multiple: bool = False,
    paginate: bool = True,
    auxiliary: bool = False,
) -> DiscoveryRule:
    return DiscoveryRule(
        service=service,
        field=field,
        action_id=action_id,
        result_path=tuple(result_path.split(".")),
        additional_result_paths=tuple(tuple(path.split(".")) for path in additional_result_paths),
        request_from=request_from,
        constants=constants,
        actions=actions,
        multiple=multiple,
        paginate=paginate,
        auxiliary=auxiliary,
    )


@dataclass(frozen=True)
class InspectionRule:
    """Explicit read-only metadata lookup for one selected resource field."""

    service: str
    field: str
    action_id: str
    request_from: tuple[tuple[str, str, bool], ...]
    constants: tuple[tuple[str, Any], ...] = ()
    actions: tuple[str, ...] = ()
    paginate: bool = False


def _inspection(
    service: str,
    field: str,
    action_id: str,
    *,
    request_from: tuple[tuple[str, str, bool], ...],
    constants: tuple[tuple[str, Any], ...] = (),
    actions: tuple[str, ...] = (),
    paginate: bool = False,
) -> InspectionRule:
    return InspectionRule(
        service=service,
        field=field,
        action_id=action_id,
        request_from=request_from,
        constants=constants,
        actions=actions,
        paginate=paginate,
    )


DISCOVERY_RULES = (
    _rule("dynamodb", "TableName", "dynamodb.list_tables", "TableNames.*"),
    _rule(
        "dynamodb",
        "IndexName",
        "dynamodb.describe_table",
        "Table.GlobalSecondaryIndexes.*.IndexName",
        additional_result_paths=("Table.LocalSecondaryIndexes.*.IndexName",),
        request_from=(("TableName", "TableName"),),
        actions=("dynamodb.query", "dynamodb.scan"),
        paginate=False,
    ),
    _rule("sqs", "QueueUrl", "sqs.list_queues", "QueueUrls.*"),
    _rule(
        "sqs",
        "SourceQueueUrl",
        "sqs.list_queues",
        "QueueUrls.*",
        auxiliary=True,
    ),
    _rule(
        "sqs",
        "DestinationQueueUrl",
        "sqs.list_queues",
        "QueueUrls.*",
        auxiliary=True,
    ),
    _rule(
        "sqs",
        "SourceQueueArn",
        "sqs.get_queue_attributes",
        "Attributes.QueueArn",
        request_from=(("QueueUrl", "SourceQueueUrl"),),
        constants=(("AttributeNames", ("QueueArn",)),),
        paginate=False,
        auxiliary=True,
    ),
    _rule(
        "sqs",
        "SourceArn",
        "sqs.get_queue_attributes",
        "Attributes.QueueArn",
        request_from=(("QueueUrl", "SourceQueueUrl"),),
        constants=(("AttributeNames", ("QueueArn",)),),
        actions=("sqs.list_message_move_tasks", "sqs.start_message_move_task"),
        paginate=False,
    ),
    _rule(
        "sqs",
        "DestinationArn",
        "sqs.get_queue_attributes",
        "Attributes.QueueArn",
        request_from=(("QueueUrl", "DestinationQueueUrl"),),
        constants=(("AttributeNames", ("QueueArn",)),),
        actions=("sqs.start_message_move_task",),
        paginate=False,
    ),
    _rule(
        "sqs",
        "TaskHandle",
        "sqs.list_message_move_tasks",
        "Results.*.TaskHandle",
        request_from=(("SourceArn", "SourceQueueArn"),),
        actions=("sqs.cancel_message_move_task",),
        paginate=False,
    ),
    _rule("sns", "TopicArn", "sns.list_topics", "Topics.*.TopicArn"),
    _rule(
        "sns",
        "SubscriptionArn",
        "sns.list_subscriptions",
        "Subscriptions.*.SubscriptionArn",
        actions=("sns.unsubscribe",),
    ),
    _rule("lambda", "FunctionName", "lambda.list_functions", "Functions.*.FunctionName"),
    _rule(
        "lambda",
        "Name",
        "lambda.list_aliases",
        "Aliases.*.Name",
        request_from=(("FunctionName", "FunctionName"),),
        actions=("lambda.get_alias", "lambda.update_alias", "lambda.delete_alias"),
    ),
    _rule(
        "lambda",
        "FunctionVersion",
        "lambda.list_versions_by_function",
        "Versions.*.Version",
        request_from=(("FunctionName", "FunctionName"),),
        actions=("lambda.create_alias", "lambda.update_alias"),
    ),
    _rule(
        "lambda",
        "LayerName",
        "lambda.list_layers",
        "Layers.*.LayerName",
        actions=(
            "lambda.list_layer_versions",
            "lambda.get_layer_version",
            "lambda.publish_layer_version",
            "lambda.delete_layer_version",
        ),
    ),
    _rule(
        "lambda",
        "Qualifier",
        "lambda.list_aliases",
        "Aliases.*.Name",
        request_from=(("FunctionName", "FunctionName"),),
        actions=(
            "lambda.invoke",
            "lambda.get_function",
            "lambda.get_function_configuration",
        ),
    ),
    _rule(
        "s3",
        "S3Bucket",
        "s3.list_buckets",
        "Buckets.*.Name",
        actions=("lambda.update_function_code",),
    ),
    _rule(
        "s3",
        "S3Key",
        "s3.list_objects_v2",
        "Contents.*.Key",
        request_from=(("Bucket", "S3Bucket"),),
        actions=("lambda.update_function_code",),
    ),
    _rule("s3", "Bucket", "s3.list_buckets", "Buckets.*.Name"),
    _rule(
        "s3",
        "Key",
        "s3.list_objects_v2",
        "Contents.*.Key",
        request_from=(("Bucket", "Bucket"),),
        actions=("s3.get_object", "s3.head_object", "s3.delete_object"),
    ),
    _rule(
        "ec2",
        "InstanceIds",
        "ec2.describe_instances",
        "Reservations.*.Instances.*.InstanceId",
        multiple=True,
    ),
    _rule(
        "ec2",
        "ImageIds",
        "ec2.describe_images",
        "Images.*.ImageId",
        constants=(("Owners", ("self",)),),
        actions=("ec2.describe_images",),
        multiple=True,
        paginate=False,
    ),
    _rule("ec2", "VpcIds", "ec2.describe_vpcs", "Vpcs.*.VpcId", multiple=True),
    _rule("ec2", "SubnetIds", "ec2.describe_subnets", "Subnets.*.SubnetId", multiple=True),
    _rule(
        "ec2",
        "GroupIds",
        "ec2.describe_security_groups",
        "SecurityGroups.*.GroupId",
        multiple=True,
    ),
    _rule("ec2", "VolumeIds", "ec2.describe_volumes", "Volumes.*.VolumeId", multiple=True),
    _rule("ec2", "SnapshotIds", "ec2.describe_snapshots", "Snapshots.*.SnapshotId", multiple=True),
    _rule(
        "ec2",
        "NetworkInterfaceIds",
        "ec2.describe_network_interfaces",
        "NetworkInterfaces.*.NetworkInterfaceId",
        multiple=True,
    ),
    _rule(
        "ec2",
        "AllocationIds",
        "ec2.describe_addresses",
        "Addresses.*.AllocationId",
        multiple=True,
        paginate=False,
    ),
    _rule(
        "ec2",
        "RegionNames",
        "ec2.describe_regions",
        "Regions.*.RegionName",
        multiple=True,
        paginate=False,
    ),
    _rule(
        "ec2",
        "ZoneNames",
        "ec2.describe_availability_zones",
        "AvailabilityZones.*.ZoneName",
        multiple=True,
        paginate=False,
    ),
    _rule(
        "rds",
        "DBInstanceIdentifier",
        "rds.describe_db_instances",
        "DBInstances.*.DBInstanceIdentifier",
    ),
    _rule(
        "rds", "DBClusterIdentifier", "rds.describe_db_clusters", "DBClusters.*.DBClusterIdentifier"
    ),
    _rule(
        "rds",
        "DBSnapshotIdentifier",
        "rds.describe_db_snapshots",
        "DBSnapshots.*.DBSnapshotIdentifier",
    ),
    _rule(
        "rds",
        "DBClusterSnapshotIdentifier",
        "rds.describe_db_cluster_snapshots",
        "DBClusterSnapshots.*.DBClusterSnapshotIdentifier",
    ),
    _rule("ecs", "cluster", "ecs.list_clusters", "clusterArns.*"),
    _rule("ecs", "clusters", "ecs.list_clusters", "clusterArns.*", multiple=True),
    _rule(
        "ecs",
        "service",
        "ecs.list_services",
        "serviceArns.*",
        request_from=(("cluster", "cluster"),),
        actions=("ecs.update_service",),
    ),
    _rule(
        "ecs",
        "services",
        "ecs.list_services",
        "serviceArns.*",
        request_from=(("cluster", "cluster"),),
        multiple=True,
    ),
    _rule(
        "ecs",
        "task",
        "ecs.list_tasks",
        "taskArns.*",
        request_from=(("cluster", "cluster"),),
        actions=("ecs.stop_task",),
    ),
    _rule(
        "ecs",
        "tasks",
        "ecs.list_tasks",
        "taskArns.*",
        request_from=(("cluster", "cluster"),),
        multiple=True,
    ),
    _rule(
        "ecs",
        "taskDefinition",
        "ecs.list_task_definitions",
        "taskDefinitionArns.*",
        actions=("ecs.describe_task_definition", "ecs.update_service"),
    ),
    _rule("eks", "name", "eks.list_clusters", "clusters.*"),
    _rule("eks", "clusterName", "eks.list_clusters", "clusters.*"),
    _rule(
        "eks",
        "nodegroupName",
        "eks.list_nodegroups",
        "nodegroups.*",
        request_from=(("clusterName", "clusterName"),),
    ),
    _rule(
        "eks",
        "addonName",
        "eks.list_addons",
        "addons.*",
        request_from=(("clusterName", "clusterName"),),
    ),
    _rule("ecr", "repositoryName", "ecr.describe_repositories", "repositories.*.repositoryName"),
    _rule(
        "ecr",
        "repositoryNames",
        "ecr.describe_repositories",
        "repositories.*.repositoryName",
        multiple=True,
    ),
    _rule("events", "EventBusName", "events.list_event_buses", "EventBuses.*.Name", paginate=False),
    _rule(
        "events",
        "Name",
        "events.list_event_buses",
        "EventBuses.*.Name",
        actions=("events.describe_event_bus",),
        paginate=False,
    ),
    _rule(
        "events",
        "EndpointId",
        "events.list_endpoints",
        "Endpoints.*.EndpointId",
        actions=("events.put_events",),
    ),
    _rule(
        "events",
        "Rule",
        "events.list_rules",
        "Rules.*.Name",
        request_from=(("EventBusName", "EventBusName"),),
    ),
    _rule(
        "events",
        "Name",
        "events.list_rules",
        "Rules.*.Name",
        request_from=(("EventBusName", "EventBusName"),),
        actions=("events.describe_rule",),
    ),
    _rule(
        "stepfunctions",
        "stateMachineArn",
        "stepfunctions.list_state_machines",
        "stateMachines.*.stateMachineArn",
    ),
    _rule(
        "stepfunctions",
        "executionArn",
        "stepfunctions.list_executions",
        "executions.*.executionArn",
        request_from=(("stateMachineArn", "stateMachineArn"),),
        actions=(
            "stepfunctions.describe_execution",
            "stepfunctions.get_execution_history",
            "stepfunctions.stop_execution",
        ),
    ),
    _rule("logs", "logGroupName", "logs.describe_log_groups", "logGroups.*.logGroupName"),
    _rule(
        "logs",
        "logStreamName",
        "logs.describe_log_streams",
        "logStreams.*.logStreamName",
        request_from=(("logGroupName", "logGroupName"),),
    ),
    _rule(
        "logs",
        "logStreamNames",
        "logs.describe_log_streams",
        "logStreams.*.logStreamName",
        request_from=(("logGroupName", "logGroupName"),),
        actions=("logs.filter_log_events",),
        multiple=True,
    ),
    _rule(
        "autoscaling",
        "AutoScalingGroupName",
        "autoscaling.describe_auto_scaling_groups",
        "AutoScalingGroups.*.AutoScalingGroupName",
    ),
    _rule(
        "autoscaling",
        "AutoScalingGroupNames",
        "autoscaling.describe_auto_scaling_groups",
        "AutoScalingGroups.*.AutoScalingGroupName",
        multiple=True,
    ),
    _rule(
        "autoscaling",
        "InstanceIds",
        "autoscaling.describe_auto_scaling_instances",
        "AutoScalingInstances.*.InstanceId",
        multiple=True,
    ),
    _rule(
        "autoscaling",
        "ActivityIds",
        "autoscaling.describe_scaling_activities",
        "Activities.*.ActivityId",
        actions=("autoscaling.describe_scaling_activities",),
        multiple=True,
    ),
    _rule(
        "autoscaling",
        "PolicyNames",
        "autoscaling.describe_policies",
        "ScalingPolicies.*.PolicyName",
        request_from=(("AutoScalingGroupName", "AutoScalingGroupName"),),
        multiple=True,
    ),
    _rule(
        "elasticache",
        "CacheClusterId",
        "elasticache.describe_cache_clusters",
        "CacheClusters.*.CacheClusterId",
    ),
    _rule(
        "elasticache",
        "ReplicationGroupId",
        "elasticache.describe_replication_groups",
        "ReplicationGroups.*.ReplicationGroupId",
    ),
    _rule(
        "elasticache",
        "SnapshotName",
        "elasticache.describe_snapshots",
        "Snapshots.*.SnapshotName",
    ),
    _rule(
        "elbv2",
        "LoadBalancerArn",
        "elbv2.describe_load_balancers",
        "LoadBalancers.*.LoadBalancerArn",
    ),
    _rule(
        "elbv2",
        "LoadBalancerArns",
        "elbv2.describe_load_balancers",
        "LoadBalancers.*.LoadBalancerArn",
        multiple=True,
    ),
    _rule(
        "elbv2",
        "Names",
        "elbv2.describe_load_balancers",
        "LoadBalancers.*.LoadBalancerName",
        actions=("elbv2.describe_load_balancers",),
        multiple=True,
    ),
    _rule(
        "elbv2", "TargetGroupArn", "elbv2.describe_target_groups", "TargetGroups.*.TargetGroupArn"
    ),
    _rule(
        "elbv2",
        "TargetGroupArns",
        "elbv2.describe_target_groups",
        "TargetGroups.*.TargetGroupArn",
        multiple=True,
    ),
    _rule(
        "elbv2",
        "Names",
        "elbv2.describe_target_groups",
        "TargetGroups.*.TargetGroupName",
        actions=("elbv2.describe_target_groups",),
        multiple=True,
    ),
    _rule(
        "elbv2",
        "ListenerArns",
        "elbv2.describe_listeners",
        "Listeners.*.ListenerArn",
        request_from=(("LoadBalancerArn", "LoadBalancerArn"),),
        multiple=True,
    ),
    _rule(
        "elbv2",
        "ListenerArn",
        "elbv2.describe_listeners",
        "Listeners.*.ListenerArn",
        request_from=(("LoadBalancerArn", "LoadBalancerArn"),),
        actions=("elbv2.describe_rules",),
    ),
    _rule(
        "elbv2",
        "RuleArns",
        "elbv2.describe_rules",
        "Rules.*.RuleArn",
        request_from=(("ListenerArn", "ListenerArn"),),
        multiple=True,
    ),
    _rule(
        "cloudwatch",
        "Namespace",
        "cloudwatch.list_metrics",
        "Metrics.*.Namespace",
    ),
    _rule(
        "cloudwatch",
        "MetricName",
        "cloudwatch.list_metrics",
        "Metrics.*.MetricName",
        request_from=(("Namespace", "Namespace"),),
    ),
    _rule(
        "cloudwatch",
        "AlarmName",
        "cloudwatch.describe_alarms",
        "MetricAlarms.*.AlarmName",
        additional_result_paths=("CompositeAlarms.*.AlarmName",),
        actions=("cloudwatch.describe_alarm_history",),
    ),
    _rule(
        "cloudwatch",
        "AlarmNames",
        "cloudwatch.describe_alarms",
        "MetricAlarms.*.AlarmName",
        additional_result_paths=("CompositeAlarms.*.AlarmName",),
        actions=("cloudwatch.describe_alarms",),
        multiple=True,
    ),
    _rule(
        "cloudformation", "StackName", "cloudformation.list_stacks", "StackSummaries.*.StackName"
    ),
    _rule(
        "cloudformation",
        "LogicalResourceId",
        "cloudformation.list_stack_resources",
        "StackResourceSummaries.*.LogicalResourceId",
        request_from=(("StackName", "StackName"),),
    ),
    _rule(
        "cloudformation",
        "PhysicalResourceId",
        "cloudformation.list_stack_resources",
        "StackResourceSummaries.*.PhysicalResourceId",
        request_from=(("StackName", "StackName"),),
    ),
)


INSPECTION_RULES = (
    _inspection(
        "sqs",
        "QueueUrl",
        "sqs.get_queue_attributes",
        request_from=(("QueueUrl", "QueueUrl", False),),
        constants=(("AttributeNames", ("All",)),),
    ),
    _inspection(
        "sns",
        "TopicArn",
        "sns.get_topic_attributes",
        request_from=(("TopicArn", "TopicArn", False),),
    ),
    _inspection(
        "lambda",
        "FunctionName",
        "lambda.get_function_configuration",
        request_from=(("FunctionName", "FunctionName", False),),
    ),
    _inspection(
        "lambda",
        "Qualifier",
        "lambda.get_function_configuration",
        request_from=(
            ("FunctionName", "FunctionName", False),
            ("Qualifier", "Qualifier", False),
        ),
        actions=("lambda.invoke", "lambda.get_function", "lambda.get_function_configuration"),
    ),
    _inspection(
        "s3",
        "Bucket",
        "s3.head_bucket",
        request_from=(("Bucket", "Bucket", False),),
    ),
    _inspection(
        "ec2",
        "InstanceIds",
        "ec2.describe_instances",
        request_from=(("InstanceIds", "InstanceIds", True),),
    ),
    _inspection(
        "ec2",
        "ImageIds",
        "ec2.describe_images",
        request_from=(("ImageIds", "ImageIds", True),),
        actions=("ec2.describe_images",),
    ),
    _inspection(
        "rds",
        "DBInstanceIdentifier",
        "rds.describe_db_instances",
        request_from=(("DBInstanceIdentifier", "DBInstanceIdentifier", False),),
    ),
    _inspection(
        "rds",
        "DBClusterIdentifier",
        "rds.describe_db_clusters",
        request_from=(("DBClusterIdentifier", "DBClusterIdentifier", False),),
    ),
    _inspection(
        "ecs",
        "cluster",
        "ecs.describe_clusters",
        request_from=(("clusters", "cluster", True),),
    ),
    _inspection(
        "ecs",
        "service",
        "ecs.describe_services",
        request_from=(("cluster", "cluster", False), ("services", "service", True)),
    ),
    _inspection(
        "ecs",
        "task",
        "ecs.describe_tasks",
        request_from=(("cluster", "cluster", False), ("tasks", "task", True)),
    ),
    _inspection(
        "eks",
        "name",
        "eks.describe_cluster",
        request_from=(("name", "name", False),),
    ),
    _inspection(
        "eks",
        "clusterName",
        "eks.describe_cluster",
        request_from=(("name", "clusterName", False),),
    ),
    _inspection(
        "eks",
        "nodegroupName",
        "eks.describe_nodegroup",
        request_from=(
            ("clusterName", "clusterName", False),
            ("nodegroupName", "nodegroupName", False),
        ),
    ),
    _inspection(
        "eks",
        "addonName",
        "eks.describe_addon",
        request_from=(
            ("clusterName", "clusterName", False),
            ("addonName", "addonName", False),
        ),
    ),
    _inspection(
        "ecr",
        "repositoryName",
        "ecr.describe_repositories",
        request_from=(("repositoryNames", "repositoryName", True),),
    ),
    _inspection(
        "events",
        "EventBusName",
        "events.describe_event_bus",
        request_from=(("Name", "EventBusName", False),),
    ),
    _inspection(
        "stepfunctions",
        "stateMachineArn",
        "stepfunctions.describe_state_machine",
        request_from=(("stateMachineArn", "stateMachineArn", False),),
    ),
    _inspection(
        "stepfunctions",
        "executionArn",
        "stepfunctions.describe_execution",
        request_from=(("executionArn", "executionArn", False),),
        actions=(
            "stepfunctions.describe_execution",
            "stepfunctions.get_execution_history",
            "stepfunctions.stop_execution",
        ),
    ),
    _inspection(
        "autoscaling",
        "AutoScalingGroupName",
        "autoscaling.describe_auto_scaling_groups",
        request_from=(("AutoScalingGroupNames", "AutoScalingGroupName", True),),
    ),
    _inspection(
        "elasticache",
        "CacheClusterId",
        "elasticache.describe_cache_clusters",
        request_from=(("CacheClusterId", "CacheClusterId", False),),
    ),
    _inspection(
        "elasticache",
        "ReplicationGroupId",
        "elasticache.describe_replication_groups",
        request_from=(("ReplicationGroupId", "ReplicationGroupId", False),),
    ),
    _inspection(
        "elbv2",
        "LoadBalancerArn",
        "elbv2.describe_load_balancers",
        request_from=(("LoadBalancerArns", "LoadBalancerArn", True),),
    ),
    _inspection(
        "elbv2",
        "TargetGroupArn",
        "elbv2.describe_target_groups",
        request_from=(("TargetGroupArns", "TargetGroupArn", True),),
    ),
    _inspection(
        "cloudformation",
        "StackName",
        "cloudformation.describe_stacks",
        request_from=(("StackName", "StackName", False),),
    ),
)


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


def discovery_services() -> list[str]:
    """Services with at least one dependency-free read suitable for the standalone explorer."""
    return sorted(
        {rule.service for rule in DISCOVERY_RULES if not rule.request_from and not rule.auxiliary}
    )


def _primary_discovery_rule(service: str) -> DiscoveryRule | None:
    return next(
        (
            rule
            for rule in DISCOVERY_RULES
            if rule.service == service and not rule.request_from and not rule.auxiliary
        ),
        None,
    )


def explore(registry: ActionRegistry, user: Identity, context: AWSContext, service: str) -> Any:
    rule = _primary_discovery_rule(service)
    if rule is None:
        # Preserve the legacy explorer contract: unknown services are not
        # accepted and fail before any provider/action lookup can occur.
        raise KeyError(service)
    return read_action(
        registry,
        user,
        context,
        rule.action_id,
        discovery_request(rule, {}),
    )


def resource_choices(service: str, result: Any) -> list[str]:
    """Extract safe selectable identifiers from the standalone service explorer."""
    rule = _primary_discovery_rule(service)
    return discovery_choices(rule, result) if rule is not None else []


def dynamodb_observed_fields(result: Any) -> list[dict[str, Any]]:
    """Summarize attributes observed in a bounded DynamoDB sample.

    DynamoDB has no table-wide column schema. These rows describe only the
    sampled items and must never be presented as authoritative table metadata.
    """
    if not isinstance(result, dict) or not isinstance(result.get("Items"), list):
        return []
    observed: dict[str, dict[str, Any]] = {}
    for item in result["Items"]:
        if not isinstance(item, dict):
            continue
        for name, value in item.items():
            if not isinstance(name, str) or not isinstance(value, dict):
                continue
            types = sorted(key for key in value if isinstance(key, str))
            entry = observed.setdefault(name, {"field": name, "types": set(), "observed": 0})
            entry["types"].update(types)
            entry["observed"] += 1
    return [
        {
            "field": name,
            "types": ", ".join(sorted(entry["types"])) or "—",
            "observed": entry["observed"],
        }
        for name, entry in sorted(observed.items())
    ]


def sample_dynamodb_fields(
    registry: ActionRegistry,
    user: Identity,
    context: AWSContext,
    table_name: str,
    *,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """Read a small, explicit sample and return observed attribute metadata."""
    if not isinstance(table_name, str) or not table_name.strip():
        raise WorkflowValidationError("DynamoDB field sampling requires a literal table name.")
    if type(limit) is not int or not 1 <= limit <= 25:
        raise WorkflowValidationError("DynamoDB field sampling limit must be between 1 and 25.")
    result = read_action(
        registry,
        user,
        context,
        "dynamodb.scan",
        {"TableName": table_name, "Limit": limit},
    )
    sampled = len(result.get("Items", [])) if isinstance(result, dict) else 0
    return dynamodb_observed_fields(result), sampled


def discovery_rules(action_id: str, input_schema: dict[str, Any]) -> list[DiscoveryRule]:
    """Return only rules that can populate top-level fields of this exact Action."""
    service = action_id.split(".", 1)[0]
    properties = input_schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    return [
        rule
        for rule in DISCOVERY_RULES
        if not rule.auxiliary
        and rule.field in properties
        and (
            (not rule.actions and rule.service == service)
            or (rule.actions and action_id in rule.actions)
        )
    ]


def supporting_discovery_rules(action_id: str, input_schema: dict[str, Any]) -> list[DiscoveryRule]:
    """Return dependency selectors needed only to discover fields of this action.

    Supporting values stay outside the runbook unless they are real action inputs.
    Parents are returned before children so the UI can build deterministic chains.
    """
    service = action_id.split(".", 1)[0]
    properties = input_schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    target_rules = discovery_rules(action_id, input_schema)
    support: list[DiscoveryRule] = []
    seen: set[str] = set()

    def add_dependency(field: str) -> None:
        if field in properties or field in seen:
            return
        seen.add(field)
        candidate = next(
            (
                rule
                for rule in DISCOVERY_RULES
                if rule.service == service and rule.field == field and not rule.actions
            ),
            None,
        )
        if candidate is None:
            return
        for _, source_field in candidate.request_from:
            add_dependency(source_field)
        support.append(candidate)

    for rule in target_rules:
        for _, source_field in rule.request_from:
            add_dependency(source_field)
    return support


def missing_dependencies(rule: DiscoveryRule, current: dict[str, Any]) -> list[str]:
    """Dependencies must already be literal values in the current discovery context."""
    missing: list[str] = []
    for _, source_field in rule.request_from:
        value = current.get(source_field)
        if not isinstance(value, str) or not value.strip() or references({source_field: value}):
            missing.append(source_field)
    return missing


def discovery_request(rule: DiscoveryRule, current: dict[str, Any]) -> dict[str, Any]:
    missing = missing_dependencies(rule, current)
    if missing:
        raise WorkflowValidationError(
            "Resource discovery requires literal values for: " + ", ".join(missing)
        )
    request = {
        request_name: current[source_field] for request_name, source_field in rule.request_from
    }
    for name, value in rule.constants:
        request[name] = list(value) if isinstance(value, tuple) else value
    if rule.paginate:
        request["_flowops"] = {"paginate": True, "max_items": 100, "max_pages": 3}
    return request


def _path_values(value: Any, path: tuple[str, ...]) -> list[Any]:
    values = [value]
    for part in path:
        next_values: list[Any] = []
        for current in values:
            if part == "*":
                if isinstance(current, list):
                    next_values.extend(current)
            elif isinstance(current, dict) and part in current:
                next_values.append(current[part])
        values = next_values
    return values


def discovery_choices(rule: DiscoveryRule, result: Any) -> list[str]:
    """Extract only string identifiers from the declared bounded response paths."""
    paths = (rule.result_path, *rule.additional_result_paths)
    return sorted(
        {
            value
            for path in paths
            for value in _path_values(result, path)
            if isinstance(value, str) and value
        }
    )


def discover_field(
    registry: ActionRegistry,
    user: Identity,
    context: AWSContext,
    rule: DiscoveryRule,
    current: dict[str, Any],
) -> list[str]:
    """Discover selectable values through one declared read-only AWS operation."""
    result = read_action(
        registry,
        user,
        context,
        rule.action_id,
        discovery_request(rule, current),
    )
    return discovery_choices(rule, result)


def inspection_rules(action_id: str, input_schema: dict[str, Any]) -> list[InspectionRule]:
    """Return metadata lookups applicable to selectable fields of this Action."""
    service = action_id.split(".", 1)[0]
    properties = input_schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    return [
        rule
        for rule in INSPECTION_RULES
        if rule.service == service
        and rule.field in properties
        and (not rule.actions or action_id in rule.actions)
    ]


def inspection_request(
    rule: InspectionRule, current: dict[str, Any], selected: Any
) -> dict[str, Any]:
    """Build one literal metadata request from the selected value and node context."""
    values = dict(current)
    values[rule.field] = selected
    request: dict[str, Any] = {}
    missing: list[str] = []
    for request_name, source_field, as_list in rule.request_from:
        value = values.get(source_field)
        candidates = value if isinstance(value, list) else [value]
        valid = bool(candidates) and all(
            isinstance(item, str) and item.strip() for item in candidates
        )
        if not valid or references({source_field: value}):
            missing.append(source_field)
            continue
        request[request_name] = list(candidates) if as_list else candidates[0]
    if missing:
        raise WorkflowValidationError(
            "Resource inspection requires literal values for: " + ", ".join(missing)
        )
    for name, value in rule.constants:
        request[name] = list(value) if isinstance(value, tuple) else value
    if rule.paginate:
        request["_flowops"] = {"paginate": True, "max_items": 100, "max_pages": 3}
    return request


def inspect_resource(
    registry: ActionRegistry,
    user: Identity,
    context: AWSContext,
    rule: InspectionRule,
    current: dict[str, Any],
    selected: Any,
) -> Any:
    """Load bounded metadata for one explicitly selected resource."""
    return read_action(
        registry,
        user,
        context,
        rule.action_id,
        inspection_request(rule, current, selected),
    )
