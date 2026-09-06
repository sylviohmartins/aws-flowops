from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flowops.domain.errors import ConflictError, WorkflowValidationError
from flowops.domain.models import AWSContext, Execution, Identity, Runbook, Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository, digest


def execution_for(
    store: ExecutionStore,
    suffix: str,
    *,
    dry_run: bool = True,
    status: Status = Status.PENDING,
) -> Execution:
    book = Runbook(name=f"Execution {suffix}")
    execution = Execution(
        runbook_id=book.id,
        runbook_version=1,
        snapshot=book,
        snapshot_hash=digest(book.model_dump()),
        actor=Identity(id="actor", roles=["ADMIN"]),
        aws_context=AWSContext(),
        dry_run=dry_run,
        status=status,
        reason="coverage",
    )
    return store.create(execution, f"token-{suffix}")


def test_repository_rejects_memory_database_and_rolls_back(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="temporary database file"):
        Repository(":memory:")

    repo = Repository(tmp_path / "rollback.db")
    with pytest.raises(RuntimeError, match="rollback"):
        with repo.transaction() as db:
            db.execute("INSERT INTO teams VALUES (?, ?)", ("team", "Team"))
            raise RuntimeError("rollback")

    with repo.transaction() as db:
        assert db.execute("SELECT id FROM teams WHERE id=?", ("team",)).fetchone() is None


def test_repository_environment_conflicts_and_missing_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "environment.db"
    monkeypatch.delenv("FLOWOPS_DATABASE_URL", raising=False)
    monkeypatch.setenv("FLOWOPS_DATABASE", str(database))
    repo = Repository.from_environment()
    assert repo.database == str(database)

    missing = Runbook(name="Missing")
    with pytest.raises(ConflictError, match="Draft no longer exists"):
        repo.save_draft(missing, "actor", expected_revision=1)
    with pytest.raises(WorkflowValidationError, match="does not exist"):
        repo.get_draft("missing")
    with pytest.raises(ConflictError, match="Save the current draft"):
        repo.publish("missing", "actor", 0)
    with pytest.raises(WorkflowValidationError, match="Publish a runbook version"):
        repo.version("missing")


def test_repository_integrity_archive_delete_versions_and_filtered_events(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "integrity.db")
    book = Runbook(name="Integrity")
    revision = repo.save_draft(book, "author")
    repo.publish(book.id, "author", revision)
    revision = repo.save_draft(book, "author", revision)
    repo.publish(book.id, "author", revision)
    assert repo.versions(book.id) == [2, 1]

    with repo.transaction() as db:
        db.execute(
            "UPDATE runbook_versions SET digest=? WHERE runbook_id=? AND version=?",
            ("tampered", book.id, 1),
        )
    with pytest.raises(ConflictError, match="integrity"):
        repo.version(book.id, 1)

    repo.archive(book.id, "author", archived=False)
    repo.archive(book.id, "author", deleted=True)
    assert repo.events(limit=1)[0]["event"] == "RUNBOOK_DELETED"

    repo.audit("actor", "EXECUTION_EVENT", {"ok": True}, "execution-1")
    repo.audit("actor", "OTHER_EVENT", {"ok": True}, "execution-2")
    filtered = repo.events("execution-1", limit=5000)
    assert len(filtered) == 1
    assert filtered[0]["event"] == "EXECUTION_EVENT"


def test_execution_store_missing_integrity_duplicate_and_history(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "execution.db")
    store = ExecutionStore(repo)
    first = execution_for(store, "one")

    duplicate = first.model_copy(update={"id": "different", "created_at": "different"})
    assert store.create(duplicate, "token-one").id == first.id
    assert store.history(limit=5000)[0].id == first.id

    with pytest.raises(WorkflowValidationError, match="does not exist"):
        store.get("missing")

    tampered = first.model_copy(update={"snapshot_hash": "invalid"})
    with repo.transaction() as db:
        db.execute(
            "UPDATE executions SET body=? WHERE id=?",
            (tampered.model_dump_json(), first.id),
        )
    with pytest.raises(ConflictError, match="snapshot integrity"):
        store.get(first.id)


def test_execution_claim_lock_waiting_release_and_terminal_release(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "locks.db")
    store = ExecutionStore(repo)
    first = execution_for(store, "first", dry_run=False)
    second = execution_for(store, "second", dry_run=False)

    assert store.claim("missing") is False
    assert store.claim(first.id) is True
    assert store.claim(second.id) is False

    running = store.get(first.id)
    running.status = Status.WAITING_APPROVAL
    store.save(running)
    assert store.claim(second.id) is True

    second_running = store.get(second.id)
    second_running.status = Status.SUCCESS
    store.save(second_running)
    with repo.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_locks").fetchone()[0] == 0


def test_execution_checkpoint_cancel_and_non_mapping_detail(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "cancel.db")
    store = ExecutionStore(repo)
    execution = execution_for(store, "cancel", dry_run=False)

    assert store.cancelled("missing") is False
    store.checkpoint(execution, "node", Status.SUCCESS, ["value"])  # type: ignore[arg-type]
    with repo.transaction() as db:
        row = db.execute(
            "SELECT body,status FROM node_executions WHERE execution_id=? AND node_id=?",
            (execution.id, "node"),
        ).fetchone()
    assert json.loads(row["body"]) == ["value"]
    assert row["status"] == Status.SUCCESS.value

    assert store.claim(execution.id) is True
    store.cancel(execution.id, "operator")
    assert store.cancelled(execution.id) is True
    assert store.get(execution.id).status == Status.RUNNING


def test_execution_approval_duplicate_reject_and_invalid_state_rolls_back(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "approval.db")
    store = ExecutionStore(repo)
    execution = execution_for(store, "approval")

    assert store.approval(execution, "node", "digest", {"preview": True}) == "PENDING"
    assert store.approval(execution, "node", "digest", {"preview": True}) == "PENDING"

    with pytest.raises(ConflictError, match="not waiting for approval"):
        store.decide(execution.id, "node", "digest", "approver", True, "reviewed")
    assert store.pending_approvals()[0]["decision"] == "PENDING"

    execution = store.get(execution.id)
    execution.status = Status.WAITING_APPROVAL
    store.save(execution)
    store.decide(execution.id, "node", "digest", "approver", False, "unsafe")
    rejected = store.get(execution.id)
    assert rejected.status == Status.CANCELLED
    assert rejected.finished_at is not None
    assert store.pending_approvals() == []

    with pytest.raises(ConflictError, match="already decided"):
        store.decide(execution.id, "node", "digest", "approver", False, "again")


def test_execution_checkpoint_event_copies_safe_operational_fields(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "checkpoint.db")
    store = ExecutionStore(repo)
    execution = execution_for(store, "checkpoint")
    detail: dict[str, Any] = {
        "action": "aws.s3.list_buckets",
        "service": "s3",
        "attempts": 2,
        "duration_seconds": 0.1,
        "error": "none",
        "ignored": "not promoted",
    }
    store.checkpoint(execution, "node", Status.FAILED, detail)
    event = repo.events(execution.id, limit=1)[0]
    assert event["event"] == "NODE_FAILED"
    assert event["body"]["attempts"] == 2
    assert "ignored" not in event["body"]
