"""Enhanced operations workspace layered over the stable Streamlit UI.

Only pages requiring richer production ergonomics are overridden. The base UI remains the
compatibility surface for runbook management, approvals, audit and resource exploration.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from flowops.core.mapping import apply_mapping, defaults_from_schema, flatten_schema, source_fields
from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Status, new_id
from flowops.observability import metric_snapshot
from flowops.streamlit.canvas import workflow_canvas
from flowops.streamlit.ui import FlowOpsUI

STATUS_SYMBOL = {
    Status.PENDING.value: "○",
    Status.RUNNING.value: "◉",
    Status.SUCCESS.value: "✓",
    Status.FAILED.value: "✕",
    Status.WAITING_APPROVAL.value: "⚠",
    Status.CANCELLED.value: "⊘",
    Status.SKIPPED.value: "⊘",
}


def _compatible(source: str, target: str) -> bool:
    return (
        source in {target, "any"} or target == "any" or (source == "integer" and target == "number")
    )


def _duration(started: str | None, finished: str | None) -> float | None:
    if not started or not finished:
        return None
    try:
        return max(
            0.0,
            (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(),
        )
    except ValueError:
        return None


class FlowOpsWorkspaceUI(FlowOpsUI):
    """Production-oriented pages with mapper, filters, visual status and metrics."""

    def __init__(
        self,
        user: Any,
        aws_context: Any,
        runtime: Any,
        *,
        correlation_context: dict[str, str] | None = None,
    ):
        super().__init__(user, aws_context, runtime)
        self.correlation_context = dict(correlation_context or {})

    def _dashboard(self) -> None:
        import streamlit as st

        executions = self._visible_executions(500)
        runbooks = self._visible_runbooks()
        total = len(executions)
        successes = sum(execution.status == Status.SUCCESS for execution in executions)
        failures = sum(execution.status == Status.FAILED for execution in executions)
        columns = st.columns(5)
        columns[0].metric("Runbooks", len(runbooks))
        columns[1].metric("Executions", total)
        columns[2].metric("Success", successes)
        columns[3].metric("Failures", failures)
        columns[4].metric("Success rate", f"{(successes / total * 100):.1f}%" if total else "—")

        recent = executions[:100]
        node_details = {
            execution.id: self.runtime.engine.store.nodes(execution.id) for execution in recent
        }
        metrics = metric_snapshot(recent, node_details)
        with st.expander("Operational metrics", expanded=False):
            st.json(metrics, expanded=True)
            st.caption(
                "Canonical metric names are derived from durable state and can be exported by the host."
            )

        st.subheader("Recent executions")
        st.dataframe(
            [
                {
                    "id": execution.id,
                    "runbook": execution.snapshot.name,
                    "version": execution.runbook_version,
                    "environment": execution.aws_context.environment,
                    "status": execution.status.value,
                    "started": execution.started_at or execution.created_at,
                }
                for execution in executions[:10]
            ],
            width="stretch",
            hide_index=True,
        )

        usage = Counter(execution.snapshot.name for execution in executions)
        failed = Counter(
            execution.snapshot.name for execution in executions if execution.status == Status.FAILED
        )
        environments = Counter(execution.aws_context.environment for execution in executions)
        left, middle, right = st.columns(3)
        left.markdown("**Most used runbooks**")
        left.dataframe(
            [{"runbook": name, "executions": count} for name, count in usage.most_common(10)],
            width="stretch",
            hide_index=True,
        )
        middle.markdown("**Runbooks with failures**")
        middle.dataframe(
            [{"runbook": name, "failures": count} for name, count in failed.most_common(10)],
            width="stretch",
            hide_index=True,
        )
        right.markdown("**Executions by environment**")
        right.dataframe(
            [{"environment": name, "executions": count} for name, count in environments.items()],
            width="stretch",
            hide_index=True,
        )

    def _editor(self) -> None:
        import streamlit as st

        super()._editor()
        selected_id = st.session_state.get("flowops:selected_runbook")
        if not isinstance(selected_id, str):
            return
        try:
            persisted, revision = self.repository.get_draft(selected_id)
        except FlowOpsError:
            return
        working = self._working_draft(persisted, revision)
        selected_node_id = st.session_state.get(f"flowops:node:{persisted.id}")
        node = next((entry for entry in working.nodes if entry.id == selected_node_id), None)
        if node is None or node.action.startswith("core."):
            return

        metadata = self.runtime.registry.get(node.action).metadata
        targets = [field for field in flatten_schema(metadata.input_schema) if field.path != "$"]
        sources = source_fields(working, node.id, self.runtime.registry)
        st.subheader("Schema & Data Mapper")
        st.caption(
            "Source selection is restricted to parameters, execution context and ancestor outputs. "
            "Mappings use the same safe expression DSL as the engine."
        )
        with st.expander("Input schema browser", expanded=True):
            st.dataframe(
                [
                    {
                        "field": field.path,
                        "type": field.type,
                        "required": field.required,
                        "default": field.default,
                        "enum": ", ".join(map(str, field.enum)),
                        "documentation": field.description,
                    }
                    for field in targets
                ],
                width="stretch",
                hide_index=True,
            )
        if not targets:
            st.info("This action does not expose mappable input fields in its service model.")
            return
        if not sources:
            st.info("No parameter or ancestor output is available to map yet.")
            return
        target_path = st.selectbox(
            "Target field",
            [field.path for field in targets],
            key=f"flowops:mapper-target:{persisted.id}:{node.id}",
        )
        source_path = st.selectbox(
            "Source",
            [field.path for field in sources],
            format_func=lambda path: next(
                f"{field.path} · {field.type}" for field in sources if field.path == path
            ),
            key=f"flowops:mapper-source:{persisted.id}:{node.id}",
        )
        target = next(field for field in targets if field.path == target_path)
        source = next(field for field in sources if field.path == source_path)
        compatible = _compatible(source.type, target.type)
        if compatible:
            st.success(f"Type compatible: {source.type} → {target.type}")
        else:
            st.error(f"Type mismatch: {source.type} cannot map to {target.type}.")
        preview = apply_mapping(node.config, target_path, source_path)
        st.markdown("**Mapping preview**")
        st.json(preview, expanded=False)
        editable = self._granted("runbook.edit", working)
        controls = st.columns(2)
        if controls[0].button(
            "Apply mapping",
            disabled=not editable or not compatible,
            key=f"flowops:mapper-apply:{persisted.id}:{node.id}",
        ):
            node.config = preview
            self._store_working(working, revision)
            st.rerun()
        defaults = defaults_from_schema(metadata.input_schema)
        if controls[1].button(
            "Apply schema defaults",
            disabled=not editable or not defaults,
            key=f"flowops:mapper-defaults:{persisted.id}:{node.id}",
        ):
            node.config = defaults | node.config
            self._store_working(working, revision)
            st.rerun()

    def _execute(self) -> None:
        import streamlit as st

        st.header("Execute Runbook")
        draft = self._select_runbook(label="Execution runbook", published_only=True)
        if draft is None:
            return
        versions = self.repository.versions(draft.id)
        version = st.selectbox("Version", versions, key=f"flowops:execute-version:{draft.id}")
        book = self.repository.version(draft.id, version)
        require(self.user, f"runbook.execute.{self.aws.environment}", book)
        st.caption(
            "FlowOps simulation prevents mutation calls and can simulate state transitions. "
            "It is separate from any AWS service-native DryRun option."
        )
        if self.correlation_context:
            st.caption(
                "Host correlation: "
                + ", ".join(f"{key}={value}" for key, value in self.correlation_context.items())
            )
        if self.aws.environment == "production":
            st.warning(
                f"PRODUCTION target: account {self.aws.account_id}, region {self.aws.region}. "
                "Live execution requires an explicit typed confirmation."
            )
        with st.form(f"flowops:execute-form:{book.id}:{version}"):
            values = self._parameter_inputs(book)
            dry_run = st.checkbox("FlowOps simulation", value=True)
            reason = st.text_input("Reason / change reference")
            production_word = ""
            production_account = ""
            if self.aws.environment == "production":
                production_word = st.text_input("Type PRODUCTION for a live production run")
                production_account = st.text_input("Type the 12-digit target AWS account")
            submitted = st.form_submit_button("Submit execution", type="primary")
        if submitted:
            if self.aws.environment == "production" and not dry_run:
                if production_word != "PRODUCTION" or production_account != self.aws.account_id:
                    raise WorkflowValidationError(
                        "Live production execution requires PRODUCTION and the exact target account ID."
                    )
            parameters = self._coerce_parameters(values)
            execution = self.runtime.engine.submit(
                book,
                self.user,
                self.aws,
                parameters,
                token=f"ui-{new_id()}",
                dry_run=dry_run,
                reason=reason,
                correlation_context=self.correlation_context,
            )
            self.runtime.worker.enqueue(execution.id)
            st.session_state["flowops:last_execution"] = execution.id
            st.success(f"Execution {execution.id} submitted asynchronously.")
        last = st.session_state.get("flowops:last_execution")
        if isinstance(last, str):
            try:
                execution = self.runtime.engine.store.get(last)
                st.caption(f"Latest submitted status: {execution.status.value}")
            except FlowOpsError:
                pass

    def _executions(self) -> None:
        import streamlit as st

        st.header("Execution History")
        executions = self._visible_executions(2000)
        users = sorted({execution.actor.id for execution in executions})
        environments = sorted({execution.aws_context.environment for execution in executions})
        runbooks = sorted({execution.snapshot.name for execution in executions})
        accounts = sorted({execution.aws_context.account_id for execution in executions})
        row1 = st.columns(4)
        status_filter = row1[0].selectbox(
            "Status", ["ALL"] + [status.value for status in Status], key="flowops:history-status"
        )
        user_filter = row1[1].selectbox("User", ["ALL"] + users, key="flowops:history-user")
        environment_filter = row1[2].selectbox(
            "Environment", ["ALL"] + environments, key="flowops:history-environment"
        )
        account_filter = row1[3].selectbox(
            "AWS account", ["ALL"] + accounts, key="flowops:history-account"
        )
        row2 = st.columns(3)
        runbook_filter = row2[0].selectbox(
            "Runbook", ["ALL"] + runbooks, key="flowops:history-runbook"
        )
        date_from = row2[1].date_input("From", value=None, key="flowops:history-from")
        date_to = row2[2].date_input("To", value=None, key="flowops:history-to")

        def keep(execution: Any) -> bool:
            if status_filter != "ALL" and execution.status.value != status_filter:
                return False
            if user_filter != "ALL" and execution.actor.id != user_filter:
                return False
            if (
                environment_filter != "ALL"
                and execution.aws_context.environment != environment_filter
            ):
                return False
            if account_filter != "ALL" and execution.aws_context.account_id != account_filter:
                return False
            if runbook_filter != "ALL" and execution.snapshot.name != runbook_filter:
                return False
            try:
                created = datetime.fromisoformat(execution.created_at).date()
            except ValueError:
                return False
            if date_from is not None and created < date_from:
                return False
            return not (date_to is not None and created > date_to)

        executions = [execution for execution in executions if keep(execution)]
        rows = [
            {
                "id": execution.id,
                "runbook": execution.snapshot.name,
                "version": execution.runbook_version,
                "user": execution.actor.id,
                "environment": execution.aws_context.environment,
                "account": execution.aws_context.account_id,
                "started": execution.started_at or execution.created_at,
                "duration_s": _duration(execution.started_at, execution.finished_at),
                "status": execution.status.value,
            }
            for execution in executions
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        if not executions:
            return
        selected_id = st.selectbox(
            "Execution detail",
            [execution.id for execution in executions],
            key="flowops:execution-detail",
        )
        execution = next(entry for entry in executions if entry.id == selected_id)
        st.json(
            {
                "id": execution.id,
                "runbook": execution.snapshot.name,
                "version": execution.runbook_version,
                "actor": execution.actor.id,
                "environment": execution.aws_context.environment,
                "account": execution.aws_context.account_id,
                "region": execution.aws_context.region,
                "reason": execution.reason,
                "correlation_context": execution.correlation_context,
                "dry_run": execution.dry_run,
                "status": execution.status.value,
                "error": execution.error,
            },
            expanded=False,
        )
        node_details = self.runtime.engine.store.nodes(execution.id)
        visual = execution.snapshot.model_copy(deep=True)
        for node in visual.nodes:
            status = str(node_details.get(node.id, {}).get("status", Status.PENDING.value))
            node.label = f"{STATUS_SYMBOL.get(status, '○')} {node.label or node.action}"[:120]
        st.subheader("Visual execution")
        workflow_canvas(visual, key=f"flowops-execution-{execution.id}", readonly=True)

        st.subheader("Node executions")
        node_by_id = {node.id: node for node in execution.snapshot.nodes}
        node_rows: Any = [
            {
                "node": node_id,
                "action": node_by_id[node_id].action if node_id in node_by_id else node_id,
                "status": detail.get("status"),
                "attempts": detail.get("attempts"),
                "duration_s": detail.get("duration_seconds"),
                "input": json.dumps(detail.get("input"), ensure_ascii=False)[:500],
                "output": json.dumps(detail.get("output"), ensure_ascii=False)[:500],
                "error": detail.get("error"),
            }
            for node_id, detail in node_details.items()
        ]
        st.dataframe(node_rows, width="stretch", hide_index=True)
        with st.expander("Raw node details", expanded=False):
            st.json(node_details, expanded=False)
        columns = st.columns(2)
        if execution.status in {Status.PENDING, Status.RUNNING, Status.WAITING_APPROVAL}:
            if columns[0].button("Cancel", key=f"flowops:cancel:{execution.id}"):
                self.runtime.engine.cancel(execution.id, self.user)
                st.rerun()
        if execution.status in {Status.SUCCESS, Status.FAILED, Status.CANCELLED}:
            if columns[1].button("Run again", key=f"flowops:rerun:{execution.id}"):
                require(
                    self.user,
                    f"runbook.execute.{execution.aws_context.environment}",
                    execution.snapshot,
                )
                replay = self.runtime.engine.submit(
                    execution.snapshot,
                    self.user,
                    execution.aws_context,
                    execution.parameters,
                    token=f"ui-rerun-{new_id()}",
                    dry_run=execution.dry_run,
                    reason=execution.reason,
                    correlation_context=execution.correlation_context,
                )
                self.runtime.worker.enqueue(replay.id)
                st.session_state["flowops:last_execution"] = replay.id
                st.rerun()
