"""Streamlit presentation layer. All durable changes require explicit user actions."""

from __future__ import annotations

import json
from typing import Any

from flowops.application import FlowOpsRuntime
from flowops.core.graph import LOGIC_REQUIRED, validate_graph
from flowops.core.policies import permissions, require
from flowops.core.serialization import clone_runbook, export_runbook, import_runbook
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Node, Parameter, Runbook, Status, new_id
from flowops.persistence.repository import digest
from flowops.providers.aws.resources import EXPLORERS, explore
from flowops.streamlit.canvas import workflow_canvas
from flowops.templates import TEMPLATES

NAVIGATION = [
    "Dashboard",
    "Runbooks",
    "Editor",
    "Execute",
    "Executions",
    "Approvals",
    "Audit",
    "Resources",
]


class FlowOpsUI:
    def __init__(self, user: Identity, aws_context: AWSContext, runtime: FlowOpsRuntime):
        self.user = user
        self.aws = aws_context
        self.runtime = runtime
        self.repository = runtime.repository

    def render(self) -> None:
        import streamlit as st

        page = st.sidebar.radio("Navigation", NAVIGATION, key="flowops:navigation")
        st.sidebar.caption(self.user.display_name or self.user.id)
        st.sidebar.caption("Roles: " + ", ".join(self.user.roles))
        try:
            {
                "Dashboard": self._dashboard,
                "Runbooks": self._runbooks,
                "Editor": self._editor,
                "Execute": self._execute,
                "Executions": self._executions,
                "Approvals": self._approvals,
                "Audit": self._audit,
                "Resources": self._resources,
            }[page]()
        except FlowOpsError as exc:
            st.error(str(exc))

    def _granted(self, permission: str, book: Runbook | None = None) -> bool:
        try:
            require(self.user, permission, book)
            return True
        except FlowOpsError:
            return False

    def _visible_runbooks(self, query: str = "") -> list[Runbook]:
        return [
            book
            for book in self.repository.list_runbooks(query)
            if self._granted("runbook.read", book)
        ]

    def _visible_executions(self, limit: int = 1000) -> list[Any]:
        return [
            execution
            for execution in self.runtime.engine.store.history(limit)
            if self._granted("runbook.read", execution.snapshot)
        ]

    @staticmethod
    def _json_object(value: str, *, label: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}")
        except ValueError as exc:
            raise WorkflowValidationError(f"{label} must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise WorkflowValidationError(f"{label} must be a JSON object.")
        return parsed

    def _selected_id(self) -> str | None:
        import streamlit as st

        selected = st.session_state.get("flowops:selected_runbook")
        books = self._visible_runbooks()
        ids = {book.id for book in books}
        if selected not in ids:
            selected = next(iter(ids), None)
            st.session_state["flowops:selected_runbook"] = selected
        return selected

    def _select_runbook(
        self, *, label: str = "Runbook", published_only: bool = False
    ) -> Runbook | None:
        import streamlit as st

        books = self._visible_runbooks()
        if published_only:
            books = [book for book in books if self.repository.versions(book.id)]
        if not books:
            st.info("No runbooks available.")
            return None
        selected_id = self._selected_id()
        valid_ids = [book.id for book in books]
        if selected_id not in valid_ids:
            selected_id = valid_ids[0]
        labels = {book.id: f"{book.name} · {book.team}" for book in books}
        index = valid_ids.index(selected_id)
        chosen = st.selectbox(
            label,
            valid_ids,
            index=index,
            format_func=lambda value: labels[value],
            key=f"flowops:select:{label}:{published_only}",
        )
        st.session_state["flowops:selected_runbook"] = chosen
        return next(book for book in books if book.id == chosen)

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
        st.subheader("Recent executions")
        rows = [
            {
                "id": execution.id,
                "runbook": execution.snapshot.name,
                "version": execution.runbook_version,
                "environment": execution.aws_context.environment,
                "status": execution.status.value,
                "started": execution.started_at or execution.created_at,
            }
            for execution in executions[:10]
        ]
        st.dataframe(rows, width="stretch", hide_index=True)

    def _runbooks(self) -> None:
        import streamlit as st

        st.header("Runbooks")
        can_edit = self._granted("runbook.edit")
        query = st.text_input("Search", key="flowops:runbook-search")
        books = self._visible_runbooks(query)
        if can_edit:
            with st.expander("Create from template", expanded=not books):
                template_id = st.selectbox(
                    "Template",
                    list(TEMPLATES),
                    format_func=lambda key: TEMPLATES[key].name,
                    key="flowops:template",
                )
                grants = permissions(self.user)
                if "*" in grants:
                    team = st.text_input(
                        "Team",
                        value=self.user.teams[0] if self.user.teams else "default",
                        key="flowops:create-team",
                    )
                else:
                    allowed_teams = self.user.teams or ["default"]
                    team = st.selectbox("Team", allowed_teams, key="flowops:create-team")
                name = st.text_input("Name override", key="flowops:create-name")
                if st.button("Create runbook", type="primary", key="flowops:create-runbook"):
                    template = TEMPLATES[template_id]
                    book = template.create(self.user.id, team.strip() or "default")
                    if name.strip():
                        book.name = name.strip()[:160]
                    self.repository.save_draft(book, self.user.id)
                    st.session_state["flowops:selected_runbook"] = book.id
                    st.success("Runbook created as a draft.")
                    st.rerun()
        if not books:
            st.info("No runbooks match this search.")
            return
        labels = {book.id: f"{book.name} · {book.team}" for book in books}
        selected = st.selectbox(
            "Saved runbooks",
            [book.id for book in books],
            format_func=lambda value: labels[value],
            key="flowops:runbook-list",
        )
        st.session_state["flowops:selected_runbook"] = selected
        book, revision = self.repository.get_draft(selected)
        versions = self.repository.versions(book.id)
        st.caption(
            f"Draft revision {revision} · Published versions: "
            + (", ".join(f"v{version}" for version in versions) if versions else "none")
        )
        st.write(book.description or "No description.")
        st.code(book.id, language=None)
        export_format = st.radio(
            "Export format",
            ["yaml", "json"],
            horizontal=True,
            key="flowops:export-format",
        )
        st.download_button(
            "Export",
            export_runbook(book, export_format),
            file_name=f"{book.name.lower().replace(' ', '-')}.{export_format}",
            mime="application/yaml" if export_format == "yaml" else "application/json",
        )
        if can_edit:
            action_columns = st.columns(3)
            if action_columns[0].button("Clone", key="flowops:clone"):
                require(self.user, "runbook.edit", book)
                cloned = clone_runbook(book, owner=self.user.id)
                self.repository.save_draft(cloned, self.user.id)
                st.session_state["flowops:selected_runbook"] = cloned.id
                st.success("Runbook cloned.")
                st.rerun()
            if action_columns[1].button("Archive", key="flowops:archive"):
                require(self.user, "runbook.edit", book)
                self.repository.archive(book.id, self.user.id)
                st.session_state["flowops:selected_runbook"] = None
                st.rerun()
            if action_columns[2].button("Logical delete", key="flowops:delete"):
                require(self.user, "runbook.edit", book)
                self.repository.archive(book.id, self.user.id, deleted=True)
                st.session_state["flowops:selected_runbook"] = None
                st.rerun()
            uploaded = st.file_uploader("Import YAML/JSON", type=["yaml", "yml", "json"])
            if uploaded is not None and st.button("Import as new draft", key="flowops:import"):
                try:
                    text = uploaded.getvalue().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise WorkflowValidationError("Runbook import must be UTF-8 text.") from exc
                imported = import_runbook(text, owner=self.user.id)
                self.repository.save_draft(imported, self.user.id)
                st.session_state["flowops:selected_runbook"] = imported.id
                st.success("Runbook imported.")
                st.rerun()

    @staticmethod
    def _working_key(book: Runbook) -> str:
        return f"flowops:working:{book.id}"

    def _working_draft(self, book: Runbook, revision: int) -> Runbook:
        import streamlit as st

        key = self._working_key(book)
        cached = st.session_state.get(key)
        if not isinstance(cached, dict) or cached.get("revision") != revision:
            st.session_state[key] = {"revision": revision, "body": book.model_dump_json()}
            return book.model_copy(deep=True)
        return Runbook.model_validate_json(cached["body"])

    def _store_working(self, book: Runbook, revision: int) -> None:
        import streamlit as st

        st.session_state[self._working_key(book)] = {
            "revision": revision,
            "body": book.model_dump_json(),
        }

    def _editor(self) -> None:
        import streamlit as st

        st.header("Visual Runbook Editor")
        selected = self._select_runbook(label="Editor runbook")
        if selected is None:
            return
        book, revision = self.repository.get_draft(selected.id)
        require(self.user, "runbook.read", book)
        working = self._working_draft(book, revision)
        editable = self._granted("runbook.edit", book)
        with st.form(f"flowops:metadata:{book.id}"):
            name = st.text_input("Name", value=working.name, disabled=not editable)
            description = st.text_area(
                "Description", value=working.description, disabled=not editable, height=80
            )
            tags = st.text_input(
                "Tags (comma separated)", value=", ".join(working.tags), disabled=not editable
            )
            environments = st.multiselect(
                "Allowed environments",
                ["dev", "staging", "production"],
                default=working.environments,
                disabled=not editable,
            )
            metadata_applied = st.form_submit_button("Apply metadata", disabled=not editable)
        if metadata_applied:
            working.name = name.strip() or working.name
            working.description = description
            working.tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
            working.environments = environments or ["dev"]
            self._store_working(working, revision)
            st.rerun()

        st.subheader("Parameters")
        parameter_json = st.text_area(
            "Parameter schema JSON",
            value=json.dumps(
                {key: value.model_dump(mode="json") for key, value in working.parameters.items()},
                indent=2,
                ensure_ascii=False,
            ),
            height=160,
            disabled=not editable,
            key=f"flowops:parameters:{book.id}:{revision}",
        )
        if st.button(
            "Apply parameters", disabled=not editable, key=f"flowops:parameters-apply:{book.id}"
        ):
            raw = self._json_object(parameter_json, label="Parameter schema")
            working.parameters = {key: Parameter.model_validate(value) for key, value in raw.items()}
            self._store_working(working, revision)
            st.rerun()

        st.subheader("Action palette")
        logic = sorted(LOGIC_REQUIRED)
        provider = [metadata.id for metadata in self.runtime.registry.list()]
        action_id = st.selectbox(
            "Action",
            logic + provider,
            disabled=not editable,
            key=f"flowops:add-action:{book.id}",
        )
        if action_id not in LOGIC_REQUIRED:
            metadata = self.runtime.registry.get(action_id).metadata
            st.caption(
                f"{metadata.description} · risk {metadata.risk.value} · "
                f"permissions {', '.join(metadata.required_permissions) or 'provider policy'}"
            )
        if st.button(
            "Insert before End", disabled=not editable, key=f"flowops:add-node:{book.id}"
        ):
            end = next((node for node in working.nodes if node.action == "core.end"), None)
            if end is None:
                raise WorkflowValidationError("Add an End node before inserting actions.")
            node_id = f"n_{new_id()[:12]}"
            node = Node(
                id=node_id,
                action=action_id,
                label=action_id,
                position=(end.position[0] - 220, end.position[1]),
            )
            incoming = [edge for edge in working.edges if edge.target == end.id]
            working.edges = [edge for edge in working.edges if edge.target != end.id]
            for edge in incoming:
                edge.target = node_id
            working.edges.extend(incoming)
            from flowops.domain.models import Edge

            working.edges.append(Edge(source=node_id, target=end.id))
            working.nodes.append(node)
            self._store_working(working, revision)
            st.rerun()

        if working.nodes:
            selected_node_id = st.selectbox(
                "Node properties",
                [node.id for node in working.nodes],
                format_func=lambda node_id: next(
                    f"{node.label or node.id} · {node.action}"
                    for node in working.nodes
                    if node.id == node_id
                ),
                key=f"flowops:node:{book.id}",
            )
            node = next(node for node in working.nodes if node.id == selected_node_id)
            with st.form(f"flowops:node-form:{book.id}:{selected_node_id}"):
                label = st.text_input("Label", value=node.label, disabled=not editable)
                enabled = st.checkbox("Enabled", value=node.enabled, disabled=not editable)
                failure = st.selectbox(
                    "Failure policy",
                    ["STOP", "CONTINUE", "RETRY", "FAIL_BRANCH", "MANUAL_INTERVENTION"],
                    index=[
                        "STOP",
                        "CONTINUE",
                        "RETRY",
                        "FAIL_BRANCH",
                        "MANUAL_INTERVENTION",
                    ].index(node.failure_policy),
                    disabled=not editable,
                )
                config_text = st.text_area(
                    "Configuration JSON",
                    value=json.dumps(node.config, indent=2, ensure_ascii=False),
                    height=260,
                    disabled=not editable,
                )
                node_applied = st.form_submit_button(
                    "Apply node properties", disabled=not editable
                )
            if node_applied:
                parsed = self._json_object(config_text, label="Node configuration")
                node.label = label[:120]
                node.enabled = enabled
                node.failure_policy = failure
                node.config = parsed
                self._store_working(working, revision)
                st.rerun()
            if editable and node.action not in {"core.start", "core.end"}:
                if st.button(
                    "Remove selected node", key=f"flowops:remove:{book.id}:{node.id}"
                ):
                    parents = [edge.source for edge in working.edges if edge.target == node.id]
                    children = [edge.target for edge in working.edges if edge.source == node.id]
                    working.nodes = [entry for entry in working.nodes if entry.id != node.id]
                    working.edges = [
                        edge
                        for edge in working.edges
                        if edge.source != node.id and edge.target != node.id
                    ]
                    from flowops.domain.models import Edge

                    for parent in parents:
                        for child in children:
                            if parent != child:
                                working.edges.append(Edge(source=parent, target=child))
                    self._store_working(working, revision)
                    st.rerun()

        st.subheader("Canvas")
        canvas_book, _ = workflow_canvas(
            working,
            key=f"flowops-canvas-{book.id}",
            readonly=not editable,
        )
        self._store_working(canvas_book, revision)
        working = canvas_book
        dirty = digest(working.model_dump()) != digest(book.model_dump())
        if dirty:
            st.warning("Unsaved editor changes are held only in this UI session.")
        columns = st.columns(3)
        if columns[0].button("Validate", key=f"flowops:validate:{book.id}"):
            order = validate_graph(working, self.runtime.registry)
            st.success(f"Valid workflow: {len(order)} nodes.")
        if columns[1].button(
            "Save draft", disabled=not editable, key=f"flowops:save:{book.id}"
        ):
            validate_graph(working, self.runtime.registry)
            new_revision = self.repository.save_draft(working, self.user.id, revision)
            st.session_state.pop(self._working_key(book), None)
            st.success(f"Draft revision {new_revision} saved.")
            st.rerun()
        can_publish = self._granted("runbook.publish", book)
        if columns[2].button(
            "Publish version",
            disabled=not can_publish or dirty,
            key=f"flowops:publish:{book.id}",
        ):
            validate_graph(book, self.runtime.registry)
            published = self.repository.publish(book.id, self.user.id, revision)
            st.success(f"Published v{published.version}.")
            st.rerun()

    def _parameter_inputs(self, book: Runbook) -> dict[str, tuple[Parameter, Any]]:
        import streamlit as st

        values: dict[str, tuple[Parameter, Any]] = {}
        for name, spec in book.parameters.items():
            label = f"{name}{' *' if spec.required else ''}"
            default = spec.default
            if spec.type == "boolean":
                value: Any = st.checkbox(
                    label, value=bool(default) if default is not None else False
                )
            elif spec.type == "integer":
                value = st.number_input(label, value=int(default or 0), step=1)
            elif spec.type == "number":
                value = st.number_input(label, value=float(default or 0.0))
            elif spec.type in {"array", "object"}:
                empty = [] if spec.type == "array" else {}
                value = st.text_area(
                    label, value=json.dumps(default if default is not None else empty)
                )
            else:
                value = st.text_input(label, value="" if default is None else str(default))
            if spec.description:
                st.caption(spec.description)
            values[name] = (spec, value)
        return values

    @staticmethod
    def _coerce_parameters(values: dict[str, tuple[Parameter, Any]]) -> dict[str, Any]:
        supplied: dict[str, Any] = {}
        for name, (spec, value) in values.items():
            if spec.type in {"array", "object"}:
                try:
                    value = json.loads(value)
                except ValueError as exc:
                    raise WorkflowValidationError(f"Parameter {name} must be valid JSON.") from exc
            if spec.type == "string" and not spec.required and value == "":
                value = None
            supplied[name] = value
        return supplied

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
        with st.form(f"flowops:execute-form:{book.id}:{version}"):
            values = self._parameter_inputs(book)
            dry_run = st.checkbox("FlowOps simulation", value=True)
            reason = st.text_input("Reason / change reference")
            submitted = st.form_submit_button("Submit execution", type="primary")
        if submitted:
            parameters = self._coerce_parameters(values)
            execution = self.runtime.engine.submit(
                book,
                self.user,
                self.aws,
                parameters,
                token=f"ui-{new_id()}",
                dry_run=dry_run,
                reason=reason,
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
        executions = self._visible_executions(1000)
        status_filter = st.selectbox(
            "Status",
            ["ALL"] + [status.value for status in Status],
            key="flowops:history-status",
        )
        if status_filter != "ALL":
            executions = [
                execution for execution in executions if execution.status.value == status_filter
            ]
        rows = [
            {
                "id": execution.id,
                "runbook": execution.snapshot.name,
                "version": execution.runbook_version,
                "user": execution.actor.id,
                "environment": execution.aws_context.environment,
                "started": execution.started_at or execution.created_at,
                "finished": execution.finished_at,
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
                "dry_run": execution.dry_run,
                "status": execution.status.value,
                "error": execution.error,
            },
            expanded=False,
        )
        st.subheader("Node executions")
        st.json(self.runtime.engine.store.nodes(execution.id), expanded=False)
        columns = st.columns(2)
        if execution.status in {Status.PENDING, Status.RUNNING, Status.WAITING_APPROVAL}:
            if columns[0].button("Cancel", key=f"flowops:cancel:{execution.id}"):
                self.runtime.engine.store.cancel(execution.id, self.user.id)
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
                )
                self.runtime.worker.enqueue(replay.id)
                st.session_state["flowops:last_execution"] = replay.id
                st.rerun()

    def _approvals(self) -> None:
        import streamlit as st

        st.header("Approvals")
        approvals = []
        for approval in self.runtime.engine.store.pending_approvals():
            execution = self.runtime.engine.store.get(approval["execution_id"])
            permission = f"runbook.approve.{execution.aws_context.environment}"
            if self._granted(permission, execution.snapshot):
                approvals.append(approval)
        if not approvals:
            st.info("No pending approvals.")
            return
        for approval in approvals:
            body = approval["body"]
            st.subheader(f"{body.get('environment', '').upper()} · {approval['execution_id']}")
            st.json(body, expanded=False)
            reason = st.text_input(
                "Decision reason",
                key=f"flowops:approval-reason:{approval['execution_id']}:{approval['node_id']}",
            )
            columns = st.columns(2)
            if columns[0].button(
                "Approve",
                type="primary",
                key=f"flowops:approve:{approval['execution_id']}:{approval['node_id']}",
            ):
                self.runtime.engine.approve(
                    approval["execution_id"],
                    approval["node_id"],
                    approval["digest"],
                    self.user,
                    approved=True,
                    reason=reason,
                )
                self.runtime.worker.enqueue(approval["execution_id"])
                st.rerun()
            if columns[1].button(
                "Reject",
                key=f"flowops:reject:{approval['execution_id']}:{approval['node_id']}",
            ):
                self.runtime.engine.approve(
                    approval["execution_id"],
                    approval["node_id"],
                    approval["digest"],
                    self.user,
                    approved=False,
                    reason=reason,
                )
                st.rerun()

    def _audit(self) -> None:
        import streamlit as st

        st.header("Audit")
        events = self.repository.events(limit=1000)
        visible_executions = {execution.id for execution in self._visible_executions(2000)}
        visible_books = {book.id for book in self._visible_runbooks()}
        events = [
            event
            for event in events
            if (event["execution_id"] and event["execution_id"] in visible_executions)
            or (not event["execution_id"] and event["body"].get("runbook_id") in visible_books)
        ]
        event_filter = st.text_input("Event filter", key="flowops:audit-filter").strip().upper()
        if event_filter:
            events = [event for event in events if event_filter in event["event"].upper()]
        rows = [
            {
                "when": event["created_at"],
                "who": event["actor"],
                "what": event["event"],
                "execution": event["execution_id"],
                "where": " / ".join(
                    str(event["body"].get(key, ""))
                    for key in ("environment", "account", "region")
                ).strip(" /"),
                "why": event["body"].get("reason", ""),
                "result": event["body"].get("result", ""),
            }
            for event in events
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        if events:
            event_id = st.selectbox(
                "Event detail",
                [event["id"] for event in events],
                key="flowops:audit-detail",
            )
            event = next(entry for entry in events if entry["id"] == event_id)
            st.json(event, expanded=False)

    def _resources(self) -> None:
        import streamlit as st

        st.header("AWS Resource Explorer")
        if not self._granted("aws.read"):
            st.warning("Your identity does not have aws.read.")
            return
        service = st.selectbox("Service", sorted(EXPLORERS), key="flowops:resource-service")
        if st.button("Discover resources", key="flowops:resources-discover"):
            result = explore(self.runtime.registry, self.user, self.aws, service)
            st.session_state["flowops:resource-result"] = result
        result = st.session_state.get("flowops:resource-result")
        if result is not None:
            st.json(result, expanded=False)
        st.caption("Resource discovery is read-only and runs only after explicit submission.")
