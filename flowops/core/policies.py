"""Fail-closed authorization and operational policy, shared by UI and workers."""

from dataclasses import dataclass

from flowops.core.actions import Metadata
from flowops.domain.errors import AuthorizationError, PolicyViolation
from flowops.domain.models import Execution, Identity, Risk, Runbook

ROLE_PERMISSIONS = {
    "VIEWER": {"runbook.read"},
    "AUTHOR": {"runbook.read", "runbook.edit", "runbook.publish"},
    "OPERATOR": {"runbook.read", "runbook.execute.dev", "runbook.execute.staging", "aws.read", "aws.write"},
    "APPROVER": {"runbook.read", "runbook.approve.dev", "runbook.approve.staging", "runbook.approve.production"},
    "ADMIN": {"*"},
}


def permissions(user: Identity) -> set[str]:
    result = set(user.permissions)
    for role in user.roles:
        result |= ROLE_PERMISSIONS.get(role, set())
    return result


def require(user: Identity, permission: str, book: Runbook | None = None) -> None:
    grants = permissions(user)
    if "*" not in grants and permission not in grants:
        raise AuthorizationError(f"Permission required: {permission}.")
    if book and "*" not in grants and book.team not in user.teams:
        raise AuthorizationError("Runbook belongs to a different team.")


@dataclass(frozen=True)
class PolicyEngine:
    max_affected: int = 1000
    approval_threshold: int = 100
    two_person: bool = True

    def execution(self, execution: Execution) -> None:
        require(execution.actor, f"runbook.execute.{execution.aws_context.environment}", execution.snapshot)
        if execution.aws_context.environment not in execution.snapshot.environments:
            raise PolicyViolation("Runbook is not allowed in this environment.")
        if not execution.dry_run and execution.aws_context.environment == "production" and not execution.reason.strip():
            raise PolicyViolation("Production execution requires a change reason.")

    def action(self, execution: Execution, metadata: Metadata, affected: int = 1) -> bool:
        if metadata.provider == "core":
            return False
        require(execution.actor, "aws.read" if metadata.read_only else "aws.write", execution.snapshot)
        if metadata.risk == Risk.CRITICAL:
            require(execution.actor, "aws.destructive", execution.snapshot)
        if affected > self.max_affected:
            raise PolicyViolation(f"Affected-record limit exceeded ({self.max_affected}).")
        if execution.dry_run or metadata.read_only:
            return False
        return (execution.aws_context.environment == "production" or metadata.risk == Risk.CRITICAL or affected > self.approval_threshold)
