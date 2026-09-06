# Deployment

## Supported modes

### Standalone

Install the package and run the bootstrap directly:

```bash
python -m pip install -e '.[postgres]'
export FLOWOPS_DATABASE_URL='postgresql://flowops:password@db.internal:5432/flowops'
streamlit run standalone_app.py
```

The bundled standalone identity is for demo/development. A production deployment should normally embed FlowOps in the authenticated corporate Streamlit host.

### Embedded

```python
from flowops.domain.models import AWSContext
from flowops.streamlit import FlowOpsPage

FlowOpsPage(
    user=current_user,
    permissions=current_permissions,
    aws_context=AWSContext(
        environment="production",
        account_id="123456789012",
        region="sa-east-1",
        mode="aws",
        role_arn="arn:aws:iam::123456789012:role/flowops-operator",
    ),
    correlation_context={"incident": incident_id},
).render()
```

The host owns authentication and supplies trusted identity/context. FlowOps still enforces its own operation-level RBAC and policies.

## Database

Use SQLite only for local/demo or a single-process development deployment. Use PostgreSQL for shared/multi-instance deployments.

Required environment variable:

```text
FLOWOPS_DATABASE_URL=postgresql://...
```

Migrations run transactionally during repository startup and are recorded in `schema_versions`. Back up the database before upgrading production and test the target release against a restored copy when schema changes are present.

## AWS credentials

Do not deploy static access keys in source code, database rows or runbooks. Prefer:

1. workload/task/instance role;
2. AssumeRole into the target account;
3. an approved profile/Identity Center mechanism for controlled operator environments;
4. the boto3 provider chain.

`BotoBackend` validates STS account identity against the requested `AWSContext` before execution.

## IAM

Start from `docs/IAM.md`. Grant only permissions required by the curated Actions/runbooks used by a team. Keep trust policies and target resource conditions narrow. FlowOps RBAC is not a replacement for AWS IAM.

## Production guardrails

A live production mutation requires all applicable controls:

- `runbook.execute.production`;
- production allowed by the Runbook;
- reason/change reference;
- typed `PRODUCTION` confirmation and exact target account in the UI;
- `aws.write`, and `aws.destructive` for critical operations;
- policy approval when required;
- two-person approval by default;
- impact limits and bounded bulk operations.

Run FlowOps simulation first when possible. Simulation is not advertised as AWS-native DryRun.

## Worker/process model

The included `LocalWorker` provides the asynchronous boundary needed by Streamlit and is suitable for the initial deployment shape. Execution intent/checkpoints are durable, so a future external worker can replace it without changing the Runbook or UI contracts.

For more than one application process, use PostgreSQL. Live executions acquire a coarse account/region resource lock; interrupted writes are not blindly replayed.

## Observability

Set:

```text
FLOWOPS_LOG_LEVEL=INFO
```

Audit events are emitted as sanitized single-line JSON. Ship stdout/stderr using the platform collector to CloudWatch, OpenTelemetry or Datadog. Canonical metric names exposed by the dashboard/runtime include:

- `runbook_executions_total`;
- `runbook_failures_total`;
- `runbook_duration_seconds_total`;
- `node_executions_total`;
- `node_failures_total`;
- `aws_api_calls_total`.

SQS/SNS message operations propagate `FlowOpsExecutionId` and bounded host correlation fields through message attributes when technically supported, which helps correlate downstream processing and CloudTrail/application logs.

## Rollback

Application rollback means deploying the previous tested package version. Published Runbook versions and execution snapshots are immutable and should not be rewritten. Database migrations are forward-only by default; restore from backup only through an approved operational recovery procedure rather than attempting an unsafe automatic schema rollback.

## Pre-production checklist

- CI green on the exact commit being deployed;
- PostgreSQL integration test green;
- dependency/security audit green;
- IAM reviewed against actual Action metadata;
- production account/region verified;
- backup and migration plan reviewed;
- log collection verified;
- demo/staging Fix Stuck Payment flow executed successfully;
- approval identities verified as distinct where two-person rule applies.
