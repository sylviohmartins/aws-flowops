from flowops.domain.models import AWSContext, Execution, Identity, Status
from flowops.identity import StaticIdentityProvider
from flowops.observability import metric_snapshot
from flowops.persistence.repository import digest
from flowops.templates import fix_stuck_payment


def execution(status: Status) -> Execution:
    book = fix_stuck_payment("owner", "ops")
    book.version = 1
    return Execution(
        runbook_id=book.id,
        runbook_version=1,
        snapshot=book,
        snapshot_hash=digest(book.model_dump()),
        actor=Identity(id="operator", roles=["ADMIN"], teams=["ops"]),
        aws_context=AWSContext(),
        status=status,
        started_at="2026-09-06T00:00:00+00:00",
        finished_at="2026-09-06T00:00:02+00:00",
    )


def test_metric_snapshot_uses_canonical_metric_names() -> None:
    success = execution(Status.SUCCESS)
    failed = execution(Status.FAILED)
    details = {
        success.id: {
            "start": {"status": Status.SUCCESS.value},
            "get_before": {"status": Status.SUCCESS.value},
        },
        failed.id: {"get_before": {"status": Status.FAILED.value}},
    }
    metrics = metric_snapshot([success, failed], details)
    assert metrics == {
        "runbook_executions_total": 2,
        "runbook_failures_total": 1,
        "runbook_duration_seconds_total": 4.0,
        "node_executions_total": 3,
        "node_failures_total": 1,
        "aws_api_calls_total": 2,
    }


def test_static_identity_provider_returns_defensive_copy() -> None:
    provider = StaticIdentityProvider(Identity(id="demo", roles=["ADMIN"]))
    first = provider.current()
    first.roles.append("VIEWER")
    assert provider.current().roles == ["ADMIN"]
