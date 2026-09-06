import os

import pytest

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Identity, Status
from flowops.persistence.database import HybridRow, PostgresConnection
from flowops.persistence.repository import Repository
from flowops.templates import blank, fix_stuck_payment


def test_postgres_adapter_preserves_named_and_numeric_row_access() -> None:
    row = HybridRow(("id", "body"), ("abc", "{}"))
    assert row[0] == "abc"
    assert row["body"] == "{}"
    assert dict(row) == {"id": "abc", "body": "{}"}
    assert PostgresConnection.translate("SELECT * FROM x WHERE a=? AND b=?") == (
        "SELECT * FROM x WHERE a=%s AND b=%s"
    )


@pytest.mark.skipif(
    not os.getenv("FLOWOPS_TEST_POSTGRES_DSN"),
    reason="FLOWOPS_TEST_POSTGRES_DSN is required for PostgreSQL integration coverage",
)
def test_postgres_repository_and_dry_run_engine_round_trip() -> None:
    dsn = os.environ["FLOWOPS_TEST_POSTGRES_DSN"]
    repository = Repository(dsn)
    assert repository.backend == "postgres"
    assert "flowops:flowops" not in repository.database

    book = fix_stuck_payment("owner", "ops")
    revision = repository.save_draft(book, "owner")
    published = repository.publish(book.id, "owner", revision)

    runtime = FlowOpsRuntime.demo(repository)
    actor = Identity(id="operator", roles=["ADMIN"], teams=["ops"])
    execution = runtime.engine.submit(
        published,
        actor,
        AWSContext(),
        {"payment_id": "12345", "environment": "dev"},
        token="postgres-e2e",
        dry_run=True,
        reason="postgres integration test",
    )
    completed = runtime.engine.execute(execution.id)
    runtime.close()

    assert completed.status == Status.SUCCESS
    assert repository.version(book.id, published.version).id == book.id
    assert repository.events(execution.id)


@pytest.mark.skipif(
    not os.getenv("FLOWOPS_TEST_POSTGRES_DSN"),
    reason="FLOWOPS_TEST_POSTGRES_DSN is required for PostgreSQL integration coverage",
)
def test_postgres_live_execution_acquires_and_releases_scope_lock() -> None:
    dsn = os.environ["FLOWOPS_TEST_POSTGRES_DSN"]
    repository = Repository(dsn)
    book = blank("owner", "ops")
    revision = repository.save_draft(book, "owner")
    published = repository.publish(book.id, "owner", revision)

    runtime = FlowOpsRuntime.demo(repository)
    actor = Identity(id="operator", roles=["ADMIN"], teams=["ops"])
    execution = runtime.engine.submit(
        published,
        actor,
        AWSContext(),
        {},
        token="postgres-live-lock",
        dry_run=False,
        reason="exercise production-style resource lock semantics",
    )
    completed = runtime.engine.execute(execution.id)
    runtime.close()

    assert completed.status == Status.SUCCESS
    with repository.transaction() as db:
        lock = db.execute(
            "SELECT execution_id FROM resource_locks WHERE execution_id=?", (execution.id,)
        ).fetchone()
    assert lock is None
