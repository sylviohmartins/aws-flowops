"""Durable execution queue, per-node checkpoints and digest-bound approval decisions."""

from __future__ import annotations

import json
from typing import Any

from flowops.core.security import bounded_output
from flowops.domain.errors import ConflictError, WorkflowValidationError
from flowops.domain.models import Execution, Status, utcnow
from flowops.persistence.repository import Repository, canonical, digest


class ExecutionStore:
    def __init__(self, repository: Repository):
        self.repository = repository

    def create(self, execution: Execution, token: str) -> Execution:
        request_digest = digest({k: v for k, v in execution.model_dump().items() if k not in {"id", "created_at"}})
        with self.repository.transaction() as db:
            row = db.execute("SELECT body,request_digest FROM executions WHERE token=?", (token,)).fetchone()
            if row:
                if row["request_digest"] != request_digest:
                    raise ConflictError("Submission token was reused for a different request.")
                return Execution.model_validate_json(row["body"])
            db.execute("INSERT INTO executions (id,token,request_digest,runbook_id,status,body,created_at) VALUES (?,?,?,?,?,?,?)", (execution.id, token, request_digest, execution.runbook_id, execution.status.value, execution.model_dump_json(), execution.created_at))
            self.repository.event(db, execution.actor.id, "EXECUTION_REQUESTED", {"runbook_id": execution.runbook_id, "version": execution.runbook_version, "environment": execution.aws_context.environment, "account": execution.aws_context.account_id, "region": execution.aws_context.region, "reason": execution.reason, "dry_run": execution.dry_run}, execution.id)
        return execution

    def get(self, execution_id: str) -> Execution:
        with self.repository.transaction() as db:
            row = db.execute("SELECT body FROM executions WHERE id=?", (execution_id,)).fetchone()
        if row is None:
            raise WorkflowValidationError("Execution does not exist.")
        execution = Execution.model_validate_json(row["body"])
        if digest(execution.snapshot.model_dump()) != execution.snapshot_hash:
            raise ConflictError("Execution snapshot integrity check failed.")
        return execution

    def list(self, limit: int = 200) -> list[Execution]:
        with self.repository.transaction() as db:
            rows = db.execute("SELECT body FROM executions ORDER BY created_at DESC LIMIT ?", (min(limit, 2000),)).fetchall()
        return [Execution.model_validate_json(r["body"]) for r in rows]

    def claim(self, execution_id: str) -> bool:
        with self.repository.transaction() as db:
            row = db.execute("SELECT body FROM executions WHERE id=? AND status=?", (execution_id, Status.PENDING.value)).fetchone()
            if row is None:
                return False
            execution = Execution.model_validate_json(row["body"])
            scope = f"{execution.aws_context.mode}:{execution.aws_context.account_id}:{execution.aws_context.region}"
            if not execution.dry_run:
                lock = db.execute("SELECT execution_id FROM resource_locks WHERE scope=?", (scope,)).fetchone()
                if lock and lock[0] != execution_id:
                    return False
                if lock is None:
                    db.execute("INSERT INTO resource_locks VALUES (?,?)", (scope, execution_id))
            execution.status = Status.RUNNING
            execution.started_at = execution.started_at or utcnow()
            changed = db.execute("UPDATE executions SET status=?,body=?,revision=revision+1 WHERE id=? AND status=?", (Status.RUNNING.value, execution.model_dump_json(), execution_id, Status.PENDING.value)).rowcount
            if changed:
                self.repository.event(db, execution.actor.id, "EXECUTION_STARTED", {}, execution_id)
            return changed == 1

    def save(self, execution: Execution) -> None:
        with self.repository.transaction() as db:
            db.execute("UPDATE executions SET status=?,body=?,revision=revision+1 WHERE id=?", (execution.status.value, execution.model_dump_json(), execution.id))
            if execution.status in {Status.SUCCESS, Status.FAILED, Status.CANCELLED}:
                db.execute("DELETE FROM resource_locks WHERE execution_id=?", (execution.id,))
                self.repository.event(db, execution.actor.id, "EXECUTION_COMPLETED", {"status": execution.status.value, "error": execution.error}, execution.id)
            elif execution.status == Status.WAITING_APPROVAL:
                # Approval binds resolved inputs; release coarse lock while a human reviews.
                db.execute("DELETE FROM resource_locks WHERE execution_id=?", (execution.id,))

    def checkpoint(self, execution: Execution, node_id: str, status: Status, detail: dict[str, Any]) -> None:
        safe = bounded_output(detail)
        with self.repository.transaction() as db:
            db.execute("INSERT INTO node_executions VALUES (?,?,?,?) ON CONFLICT(execution_id,node_id) DO UPDATE SET status=excluded.status,body=excluded.body", (execution.id, node_id, status.value, canonical(safe)))
            self.repository.event(db, execution.actor.id, "NODE_STARTED" if status == Status.RUNNING else "NODE_FAILED" if status == Status.FAILED else "NODE_COMPLETED", {"node_id": node_id, "status": status.value}, execution.id)

    def nodes(self, execution_id: str) -> dict[str, dict[str, Any]]:
        with self.repository.transaction() as db:
            rows = db.execute("SELECT node_id,status,body FROM node_executions WHERE execution_id=?", (execution_id,)).fetchall()
        return {r["node_id"]: json.loads(r["body"]) | {"status": r["status"]} for r in rows}

    def cancelled(self, execution_id: str) -> bool:
        with self.repository.transaction() as db:
            row = db.execute("SELECT cancel_requested FROM executions WHERE id=?", (execution_id,)).fetchone()
        return bool(row and row[0])

    def cancel(self, execution_id: str, actor: str) -> None:
        with self.repository.transaction() as db:
            db.execute("UPDATE executions SET cancel_requested=1 WHERE id=?", (execution_id,))
            self.repository.event(db, actor, "EXECUTION_CANCEL_REQUESTED", {}, execution_id)
        execution = self.get(execution_id)
        if execution.status in {Status.PENDING, Status.WAITING_APPROVAL}:
            execution.status, execution.finished_at = Status.CANCELLED, utcnow()
            self.save(execution)

    def approval(self, execution: Execution, node_id: str, input_digest: str, detail: dict[str, Any]) -> str:
        with self.repository.transaction() as db:
            row = db.execute("SELECT decision FROM approvals WHERE execution_id=? AND node_id=? AND digest=?", (execution.id, node_id, input_digest)).fetchone()
            if row:
                return str(row[0])
            db.execute("INSERT INTO approvals (execution_id,node_id,digest,requester,decision,created_at) VALUES (?,?,?,?,?,?)", (execution.id, node_id, input_digest, execution.actor.id, "PENDING", utcnow()))
            self.repository.event(db, execution.actor.id, "APPROVAL_REQUESTED", {"node_id": node_id, "digest": input_digest, "preview": bounded_output(detail)}, execution.id)
        return "PENDING"

    def pending_approvals(self) -> list[dict[str, Any]]:
        with self.repository.transaction() as db:
            return [dict(r) for r in db.execute("SELECT * FROM approvals WHERE decision='PENDING' ORDER BY created_at")]

    def decide(self, execution_id: str, node_id: str, input_digest: str, actor: str, approved: bool, reason: str) -> None:
        with self.repository.transaction() as db:
            changed = db.execute("UPDATE approvals SET decision=?,approver=?,reason=?,decided_at=? WHERE execution_id=? AND node_id=? AND digest=? AND decision='PENDING'", ("APPROVED" if approved else "REJECTED", actor, reason, utcnow(), execution_id, node_id, input_digest)).rowcount
            if changed != 1:
                raise ConflictError("Approval was already decided or is no longer current.")
            row = db.execute("SELECT body FROM executions WHERE id=?", (execution_id,)).fetchone()
            execution = Execution.model_validate_json(row[0])
            if execution.status != Status.WAITING_APPROVAL:
                raise ConflictError("Execution is not waiting for approval.")
            execution.status = Status.PENDING if approved else Status.CANCELLED
            if not approved:
                execution.finished_at = utcnow()
            db.execute("UPDATE executions SET status=?,body=? WHERE id=?", (execution.status.value, execution.model_dump_json(), execution_id))
            self.repository.event(db, actor, "EXECUTION_APPROVED" if approved else "EXECUTION_REJECTED", {"node_id": node_id, "digest": input_digest, "reason": reason}, execution_id)
