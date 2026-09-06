"""Checkpointed DAG runner. Long-running work never executes during UI rendering.

Exactly-once delivery to arbitrary AWS APIs is impossible. Persist intent before calls;
keep completed checkpoints; never replay interrupted writes without reconciliation.
Read-only siblings may execute concurrently; mutations are deliberately serialized.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry, affected_records
from flowops.core.expressions import resolve
from flowops.core.graph import bind_parameters, validate_graph
from flowops.core.logic import logic
from flowops.core.policies import PolicyEngine, require
from flowops.core.security import bounded_output, reject_secrets
from flowops.domain.errors import (
    ConflictError,
    FlowOpsError,
    PolicyViolation,
    ProviderError,
    WorkflowValidationError,
)
from flowops.domain.models import (
    AWSContext,
    Execution,
    Identity,
    Node,
    RetryPolicy,
    Runbook,
    Status,
    utcnow,
)
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository, digest


@dataclass
class Outcome:
    status: Status
    output: Any = None
    branch: str = "default"
    error: str | None = None


class Engine:
    def __init__(
        self,
        repository: Repository,
        registry: ActionRegistry,
        *,
        policy: PolicyEngine | None = None,
        max_parallel: int = 4,
    ):
        self.repository, self.registry = repository, registry
        self.store = ExecutionStore(repository)
        self.policy = policy or PolicyEngine()
        self.max_parallel = max(1, min(max_parallel, 8))

    def submit(
        self,
        book: Runbook,
        actor: Identity,
        aws: AWSContext,
        parameters: dict[str, Any],
        *,
        token: str,
        dry_run: bool = True,
        reason: str = "",
        correlation_context: dict[str, str] | None = None,
    ) -> Execution:
        published = self.repository.version(book.id, book.version)
        if published != book:
            raise ConflictError("Execution requires the unchanged published version.")
        draft, _ = self.repository.get_draft(book.id)
        active = {b.id for b in self.repository.list_runbooks()}
        if draft.id not in active:
            raise PolicyViolation("Archived runbooks cannot start new executions.")
        validate_graph(book, self.registry)
        bound = bind_parameters(book, parameters)
        correlation = dict(correlation_context or {})
        if len(correlation) > 20 or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > 80
            or len(value) > 500
            for key, value in correlation.items()
        ):
            raise WorkflowValidationError(
                "Correlation context must contain up to 20 bounded strings."
            )
        reject_secrets(book.model_dump())
        reject_secrets(bound)
        reject_secrets(correlation)
        if not token or len(token) > 200:
            raise WorkflowValidationError("A bounded submission token is required.")
        execution = Execution(
            runbook_id=book.id,
            runbook_version=book.version,
            snapshot=book.model_copy(deep=True),
            snapshot_hash=digest(book.model_dump()),
            actor=actor.model_copy(deep=True),
            aws_context=aws.model_copy(deep=True),
            parameters=bound,
            correlation_context=correlation,
            dry_run=dry_run,
            reason=reason,
        )
        self.policy.execution(execution)
        return self.store.create(execution, token)

    def approve(
        self,
        execution_id: str,
        node_id: str,
        input_digest: str,
        approver: Identity,
        *,
        approved: bool,
        reason: str,
    ) -> None:
        execution = self.store.get(execution_id)
        require(
            approver, f"runbook.approve.{execution.aws_context.environment}", execution.snapshot
        )
        if self.policy.two_person and approver.id == execution.actor.id:
            raise PolicyViolation("Requester cannot approve their own execution.")
        if not reason.strip():
            raise PolicyViolation("An approval/rejection reason is required.")
        self.store.decide(execution_id, node_id, input_digest, approver.id, approved, reason)

    def cancel(self, execution_id: str, actor: Identity) -> None:
        execution = self.store.get(execution_id)
        require(actor, f"runbook.execute.{execution.aws_context.environment}", execution.snapshot)
        self.store.cancel(execution_id, actor.id)

    def execute(self, execution_id: str) -> Execution:
        if not self.store.claim(execution_id):
            return self.store.get(execution_id)
        execution = self.store.get(execution_id)
        try:
            self.policy.execution(execution)
            order = validate_graph(execution.snapshot, self.registry)
            nodes = {n.id: n for n in execution.snapshot.nodes}
            completed = self.store.nodes(execution.id)
            for key, detail in completed.items():
                status = detail["status"]
                if status == Status.SUCCESS:
                    execution.node_outputs[key] = detail.get("output")
                if status in {Status.SUCCESS, Status.FAILED}:
                    execution.node_branches[key] = detail.get("branch", "default")
            remaining = [
                key
                for key in order
                if key not in completed
                or completed[key]["status"] in {Status.WAITING_APPROVAL, Status.PENDING}
            ]
            if any(value["status"] == Status.RUNNING for value in completed.values()):
                raise PolicyViolation(
                    "Interrupted node has an uncertain outcome; reconcile before retry."
                )
            while remaining:
                if self.store.cancelled(execution.id):
                    execution.status = Status.CANCELLED
                    break
                ready = [
                    key
                    for key in remaining
                    if all(
                        e.source not in remaining
                        for e in execution.snapshot.edges
                        if e.target == key
                    )
                ]
                if not ready:
                    raise WorkflowValidationError("No runnable nodes remain.")
                runnable = []
                for key in ready:
                    incoming = [e for e in execution.snapshot.edges if e.target == key]
                    active = not incoming or any(
                        (
                            completed.get(e.source, {}).get("status") == Status.SUCCESS
                            and (
                                e.branch == "default"
                                or execution.node_branches.get(e.source) == e.branch
                            )
                        )
                        or (
                            completed.get(e.source, {}).get("status") == Status.FAILED
                            and e.branch == "failure"
                            and execution.node_branches.get(e.source) == "failure"
                        )
                        for e in incoming
                    )
                    if not active:
                        outcome = Outcome(Status.SKIPPED)
                        self._record(execution, nodes[key], outcome)
                        completed[key] = {"status": Status.SKIPPED}
                        remaining.remove(key)
                    else:
                        runnable.append(key)
                if not runnable:
                    continue
                parallel = [
                    key
                    for key in runnable
                    if not nodes[key].action.startswith("core.")
                    and self.registry.get(nodes[key].action).metadata.read_only
                ]
                batch = parallel[: self.max_parallel] if len(parallel) > 1 else runnable[:1]
                if len(batch) > 1:
                    with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
                        outcomes = list(
                            pool.map(lambda key: self._run_node(execution, nodes[key]), batch)
                        )
                else:
                    outcomes = [self._run_node(execution, nodes[batch[0]])]
                for key, outcome in zip(batch, outcomes, strict=True):
                    self._record(execution, nodes[key], outcome)
                    completed[key] = {"status": outcome.status}
                    if outcome.status == Status.WAITING_APPROVAL:
                        execution.status = Status.WAITING_APPROVAL
                        self.store.save(execution)
                        return execution
                    remaining.remove(key)
                    if outcome.branch == "stop" or outcome.status == Status.CANCELLED:
                        execution.status = Status.CANCELLED
                    if outcome.status == Status.FAILED and nodes[key].failure_policy in {
                        "STOP",
                        "RETRY",
                        "MANUAL_INTERVENTION",
                    }:
                        execution.status, execution.error = Status.FAILED, outcome.error
                self.store.save(execution)
                if execution.status in {Status.FAILED, Status.CANCELLED}:
                    break
            if execution.status == Status.RUNNING:
                unhandled_failure = any(
                    detail["status"] == Status.FAILED
                    and (key not in nodes or nodes[key].failure_policy != "FAIL_BRANCH")
                    for key, detail in completed.items()
                )
                execution.status = Status.FAILED if unhandled_failure else Status.SUCCESS
            for key in remaining:
                self.store.checkpoint(
                    execution, key, Status.SKIPPED, {"reason": "Execution stopped"}
                )
        except FlowOpsError as exc:
            execution.status, execution.error = Status.FAILED, str(exc)
        except Exception:
            execution.status, execution.error = (
                Status.FAILED,
                "Internal execution error; consult audit by execution ID.",
            )
        execution.finished_at = utcnow()
        self.store.save(execution)
        return execution

    def _scope(self, execution: Execution, node: Node) -> dict[str, Any]:
        parents = [e.source for e in execution.snapshot.edges if e.target == node.id]
        return {
            "params": execution.parameters,
            "context": {
                "execution_id": execution.id,
                "environment": execution.aws_context.environment,
                "account": execution.aws_context.account_id,
                "region": execution.aws_context.region,
                **execution.correlation_context,
            },
            "nodes": {key: {"output": value} for key, value in execution.node_outputs.items()},
            "input": {
                key: execution.node_outputs[key] for key in parents if key in execution.node_outputs
            },
        }

    def _record(self, execution: Execution, node: Node, outcome: Outcome) -> None:
        if outcome.status == Status.SUCCESS:
            execution.node_outputs[node.id] = outcome.output
        if outcome.status in {Status.SUCCESS, Status.FAILED}:
            execution.node_branches[node.id] = outcome.branch
        detail = self.store.nodes(execution.id).get(node.id, {})
        detail.update(
            {
                "output": outcome.output,
                "branch": outcome.branch,
                "error": outcome.error,
                "finished_at": utcnow(),
            }
        )
        self.store.checkpoint(execution, node.id, outcome.status, detail)

    def _run_node(self, execution: Execution, node: Node) -> Outcome:
        if not node.enabled:
            return Outcome(Status.SUCCESS, {"disabled": True})
        prior = self.store.nodes(execution.id).get(node.id, {})
        if prior.get("intervention"):
            return self._intervention(execution, node, prior)
        started = time.monotonic()
        scope = self._scope(execution, node)
        raw = dict(node.config)
        template = (
            raw.pop("template", None) if node.action in {"core.map", "core.for_each"} else None
        )
        service = "core" if node.action.startswith("core.") else node.action.split(".", 1)[0]
        detail: dict[str, Any] = {
            "started_at": utcnow(),
            "attempts": 0,
            "action": node.action,
            "service": service,
        }
        try:
            config = resolve(raw, scope)
            if template is not None:
                config["template"] = template
            detail["input"] = bounded_output(config)
            self.store.checkpoint(execution, node.id, Status.RUNNING, detail)
            if node.action == "core.approval":
                outcome = self._approval(
                    execution,
                    node,
                    config,
                    {
                        "message": config.get("message", "Manual checkpoint"),
                        "upstream": scope["input"],
                    },
                )
            elif node.action == "core.wait":
                seconds = config["seconds"]
                if type(seconds) not in {int, float} or not 0 <= seconds <= 3600:
                    raise WorkflowValidationError("Wait must be between 0 and 3600 seconds.")
                deadline = time.monotonic() + (0 if execution.dry_run else seconds)
                while time.monotonic() < deadline:
                    if self.store.cancelled(execution.id):
                        return Outcome(Status.CANCELLED)
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                outcome = Outcome(
                    Status.SUCCESS, {"waited_seconds": 0 if execution.dry_run else seconds}
                )
            elif node.action in {"core.retry", "core.compensation"}:
                nested = Node(
                    id=node.id,
                    action=config["action"],
                    config=config["config"],
                    retry=RetryPolicy.model_validate(config.get("retry", node.retry.model_dump())),
                )
                outcome = self._action(execution, nested, nested.config, detail)
            elif node.action == "core.for_each" and config.get("action"):
                mapped, _ = logic(node.action, config, scope, self.policy.max_affected)
                action = self.registry.get(config["action"])
                affected = 0
                for item in mapped["items"]:
                    action.validate(item)
                    affected += affected_records(action, item)
                needs_approval = self.policy.action(execution, action.metadata, affected)
                if needs_approval:
                    gate = self._approval(execution, node, config, {
                        "action": action.metadata.id, "affected": affected,
                        "risk": action.metadata.risk.value, "items": mapped["items"],
                    })
                    if gate.status != Status.SUCCESS:
                        return gate
                results = []
                for index, item in enumerate(mapped["items"]):
                    child = Node(
                        id=f"{node.id[:48]}__{index}",
                        action=config["action"],
                        config=item,
                        retry=node.retry,
                    )
                    prior = self.store.nodes(execution.id).get(child.id)
                    if prior and prior["status"] == Status.SUCCESS:
                        results.append(prior["output"])
                        continue
                    try:
                        item_result = self._action(execution, child, item, detail, approval_checked=True)
                    except FlowOpsError as exc:
                        self.store.checkpoint(execution, child.id, Status.FAILED, {"error": str(exc), "input": item})
                        raise
                    self._record(execution, child, item_result)
                    if item_result.status != Status.SUCCESS:
                        return item_result
                    results.append(item_result.output)
                outcome = Outcome(Status.SUCCESS, {"items": results})
            elif node.action.startswith("core."):
                output, branch = logic(node.action, config, scope, self.policy.max_affected)
                outcome = Outcome(
                    Status.SUCCESS,
                    output,
                    "default" if node.action == "core.validation" else branch,
                )
            else:
                outcome = self._action(execution, node, config, detail)
            outcome.output = bounded_output(outcome.output)
            detail["duration_seconds"] = time.monotonic() - started
            detail["attempts"] = max(1, detail["attempts"])
            # Persist terminal state and its output together. A crash between this write
            # and _record must never leave a successful checkpoint without its result.
            detail.update(output=outcome.output, branch=outcome.branch, error=outcome.error)
            self.store.checkpoint(execution, node.id, outcome.status, detail)
            return outcome
        except FlowOpsError as exc:
            detail["duration_seconds"] = time.monotonic() - started
            detail["error"] = str(exc)
            if isinstance(exc, ProviderError):
                detail["provider_details"] = bounded_output(exc.details)
            self.store.checkpoint(execution, node.id, Status.FAILED, detail)
            if node.failure_policy == "MANUAL_INTERVENTION" and isinstance(exc, ProviderError) and not execution.dry_run:
                detail["intervention"] = True
                return self._intervention(execution, node, detail)
            if node.failure_policy == "CONTINUE":
                return Outcome(Status.SUCCESS, {"error": str(exc), "failed": True})
            return Outcome(
                Status.FAILED,
                branch="failure" if node.failure_policy == "FAIL_BRANCH" else "default",
                error=str(exc),
            )
        except Exception:
            return Outcome(
                Status.FAILED,
                branch="failure" if node.failure_policy == "FAIL_BRANCH" else "default",
                error="Invalid action input or unexpected provider failure.",
            )

    def _intervention(self, execution: Execution, node: Node, detail: dict[str, Any]) -> Outcome:
        """A reviewer attests external reconciliation; the failed call is never replayed."""
        gate = self._approval(execution, node, detail.get("input", {}), {
            "manual_intervention": True,
            "error": detail.get("error"),
            "provider_details": detail.get("provider_details"),
            "instruction": "Approve only after external reconciliation. Continue without replaying the failed action; no AWS result is fabricated.",
        })
        gate.output = {"manual_intervention": True, "reconciled": gate.status == Status.SUCCESS}
        gate.error = detail.get("error")
        detail.update(output=gate.output, branch=gate.branch)
        self.store.checkpoint(execution, node.id, gate.status, detail)
        return gate

    def _approval(
        self, execution: Execution, node: Node, config: dict[str, Any], preview: dict[str, Any]
    ) -> Outcome:
        if execution.dry_run:
            return Outcome(
                Status.SUCCESS,
                {"simulation": True, "approval_required_live": True, "preview": preview},
            )
        bound = digest(
            {
                "snapshot": execution.snapshot_hash,
                "context": execution.aws_context.model_dump(),
                "node": node.id,
                "config": config,
                "preview": preview,
            }
        )
        decision = self.store.approval(execution, node.id, bound, preview)
        if decision == "REJECTED":
            raise PolicyViolation("Execution approval was rejected.")
        return Outcome(
            Status.SUCCESS if decision == "APPROVED" else Status.WAITING_APPROVAL,
            {"approved": decision == "APPROVED", "digest": bound},
        )

    def _action(
        self, execution: Execution, node: Node, config: dict[str, Any], detail: dict[str, Any],
        *, approval_checked: bool = False,
    ) -> Outcome:
        action = self.registry.get(node.action)
        action.validate(config)
        affected = affected_records(action, config)
        needs_approval = self.policy.action(execution, action.metadata, affected)
        context = ActionContext(
            execution.id,
            node.id,
            execution.aws_context,
            execution.dry_run,
            execution.correlation_context,
        )
        if needs_approval and not approval_checked:
            gate = self._approval(
                execution,
                node,
                config,
                {
                    "action": action.metadata.id,
                    "affected": affected,
                    "risk": action.metadata.risk.value,
                    "parameters": config,
                },
            )
            if gate.status != Status.SUCCESS:
                return gate
        attempts = node.retry.max_attempts
        if attempts > 1 and not action.metadata.idempotent:
            raise PolicyViolation("Automatic retries require an idempotent action.")
        for attempt in range(1, attempts + 1):
            detail["attempts"] = attempt
            self.store.checkpoint(execution, node.id, Status.RUNNING, detail)
            try:
                if execution.dry_run and not action.metadata.read_only:
                    return Outcome(Status.SUCCESS, action.preview(config, context))
                return Outcome(Status.SUCCESS, action.execute(config, context))
            except ProviderError as exc:
                if not (
                    exc.retryable
                    and exc.code in node.retry.retry_codes
                    and attempt < attempts
                    and action.metadata.idempotent
                ):
                    raise
                time.sleep(min(10, node.retry.backoff_seconds * 2 ** (attempt - 1)))
        raise ProviderError("Retry budget exhausted")
