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
from flowops.domain.models import Node, Runbook, Status, new_id
from flowops.observability import metric_snapshot
from flowops.streamlit.lambda_review import render_lambda_review
from flowops.streamlit.live_execution import render_live_execution
from flowops.streamlit.localization import (
    display,
    field_help,
    presentation_rows,
    render_summary_table,
)
from flowops.streamlit.node_editor import render_logic_inputs
from flowops.streamlit.resource_picker import render_resource_picker
from flowops.streamlit.typed_inputs import render_typed_inputs
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

        st.header("Visão geral")
        executions = self._visible_executions(500)
        runbooks = self._visible_runbooks()
        total = len(executions)
        successes = sum(execution.status == Status.SUCCESS for execution in executions)
        failures = sum(execution.status == Status.FAILED for execution in executions)
        columns = st.columns(5)
        columns[0].metric("Procedimentos", len(runbooks))
        columns[1].metric("Execuções", total)
        columns[2].metric("Sucesso", successes)
        columns[3].metric("Falhas", failures)
        columns[4].metric(
            "Taxa de sucesso",
            f"{(successes / total * 100):.1f}%".replace(".", ",") if total else "—",
        )

        recent = executions[:100]
        node_details = {
            execution.id: self.runtime.engine.store.nodes(execution.id) for execution in recent
        }
        metrics = metric_snapshot(recent, node_details)
        with st.expander("Métricas operacionais", expanded=False):
            st.json(metrics, expanded=True)
            st.caption(
                "As métricas são calculadas a partir do estado persistido. Seus identificadores técnicos podem ser exportados pela aplicação hospedeira."
            )

        st.subheader("Execuções recentes")
        render_summary_table(
            presentation_rows(
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
                ]
            ),
            width="stretch",
            hide_index=True,
        )

        usage = Counter(execution.snapshot.name for execution in executions)
        failed = Counter(
            execution.snapshot.name for execution in executions if execution.status == Status.FAILED
        )
        environments = Counter(execution.aws_context.environment for execution in executions)
        left, middle, right = st.columns(3)
        left.markdown("**Procedimentos mais utilizados**")
        render_summary_table(
            presentation_rows(
                [{"runbook": name, "executions": count} for name, count in usage.most_common(10)]
            ),
            container=left,
            width="stretch",
            hide_index=True,
        )
        middle.markdown("**Procedimentos com falhas**")
        render_summary_table(
            presentation_rows(
                [{"runbook": name, "failures": count} for name, count in failed.most_common(10)]
            ),
            container=middle,
            width="stretch",
            hide_index=True,
        )
        right.markdown("**Execuções por ambiente**")
        render_summary_table(
            presentation_rows(
                [{"environment": name, "executions": count} for name, count in environments.items()]
            ),
            container=right,
            width="stretch",
            hide_index=True,
        )

    def _editor(self) -> None:
        import streamlit as st

        super()._editor()
        selected_id = st.session_state.get("flowops:selected_runbook")
        if not isinstance(selected_id, str):
            return
        if st.session_state.get(f"flowops:editor-view:{selected_id}") == "Assistente":
            return
        try:
            persisted, revision = self.repository.get_draft(selected_id)
        except FlowOpsError:
            return
        cached = st.session_state.get(self._working_key(persisted))
        if isinstance(cached, dict) and cached.get("revision") != revision:
            return
        working = self._working_draft(persisted, revision)
        selected_node_id = st.session_state.get(f"flowops:node:{persisted.id}")
        node = next((entry for entry in working.nodes if entry.id == selected_node_id), None)
        if node is None or node.action.startswith("core."):
            return

        if st.session_state.get(f"flowops:node-dialog:{persisted.id}"):
            return
        with st.expander("Ferramentas avançadas da etapa", expanded=False):
            self._node_tools(working, node, revision)

    def _node_tools(self, working: Runbook, node: Node, revision: int) -> None:
        import streamlit as st

        if node.action.startswith("core."):
            render_logic_inputs(self, working, node, revision)
            return
        persisted = working
        render_typed_inputs(self, working, node, revision)
        with st.expander("Buscar recursos e montar consulta DynamoDB", expanded=False):
            render_resource_picker(self, working, node, revision)
        render_lambda_review(self, working, node, revision)

        metadata = self.runtime.registry.get(node.action).metadata
        targets = [field for field in flatten_schema(metadata.input_schema) if field.path != "$"]
        sources = source_fields(working, node.id, self.runtime.registry)
        st.subheader("Estrutura e mapeamento de dados")
        st.caption(
            "A origem deve ser um parâmetro, o contexto da execução ou a saída de uma etapa anterior. Os mapeamentos usam a mesma linguagem segura de expressões do motor de execução."
        )
        with st.expander("Estrutura dos campos de entrada", expanded=True):
            render_summary_table(
                presentation_rows(
                    [
                        {
                            "field": field.path,
                            "type": field.type,
                            "required": field.required,
                            "default": field.default,
                            "enum": ", ".join(map(str, field.enum)),
                            "documentation": field_help(field.path, {"type": field.type}),
                        }
                        for field in targets
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        if not targets:
            st.info("Esta ação não disponibiliza campos de entrada mapeáveis no modelo do serviço.")
            return
        if not sources:
            st.info(
                "Ainda não há parâmetros ou saídas de etapas anteriores disponíveis para mapear."
            )
            return
        target_path = st.selectbox(
            "Campo de destino",
            [field.path for field in targets],
            key=f"flowops:mapper-target:{persisted.id}:{node.id}",
        )
        source_path = st.selectbox(
            "Origem",
            [field.path for field in sources],
            format_func=lambda path: next(
                f"{field.path} · {display(field.type)}" for field in sources if field.path == path
            ),
            key=f"flowops:mapper-source:{persisted.id}:{node.id}",
        )
        target = next(field for field in targets if field.path == target_path)
        source = next(field for field in sources if field.path == source_path)
        compatible = _compatible(source.type, target.type)
        if "any" in {source.type, target.type}:
            st.info(
                "Tipo ainda desconhecido; a compatibilidade será conferida quando houver dados."
            )
        elif compatible:
            st.success(f"Tipos compatíveis: {display(source.type)} → {display(target.type)}")
        else:
            st.error(
                f"Tipos incompatíveis: {display(source.type)} não pode ser mapeado para {display(target.type)}."
            )
        preview = apply_mapping(node.config, target_path, source_path)
        st.markdown("**Prévia do mapeamento**")
        st.json(preview, expanded=False)
        editable = self._granted("runbook.edit", working)
        controls = st.columns(2)
        if controls[0].button(
            "Aplicar mapeamento",
            disabled=not editable or not compatible,
            key=f"flowops:mapper-apply:{persisted.id}:{node.id}",
        ):
            require(self.user, "runbook.edit", working)
            node.config = preview
            self._store_working(working, revision)
            st.rerun()
        defaults = defaults_from_schema(metadata.input_schema)
        if controls[1].button(
            "Aplicar valores padrão da estrutura",
            disabled=not editable or not defaults,
            key=f"flowops:mapper-defaults:{persisted.id}:{node.id}",
        ):
            require(self.user, "runbook.edit", working)
            node.config = defaults | node.config
            self._store_working(working, revision)
            st.rerun()

    def _execute(self) -> None:
        import streamlit as st

        st.header("Executar procedimento")
        draft = self._select_runbook(label="Procedimento a executar", published_only=True)
        if draft is None:
            return
        versions = self.repository.versions(draft.id)
        version = st.selectbox("Versão", versions, key=f"flowops:execute-version:{draft.id}")
        book = self.repository.version(draft.id, version)
        require(self.user, f"runbook.execute.{self.aws.environment}", book)
        st.caption(
            "A simulação do FlowOps impede chamadas de alteração e pode simular mudanças de estado. Ela é independente da opção DryRun nativa dos serviços AWS."
        )
        if self.correlation_context:
            st.caption(
                "Correlação da aplicação hospedeira: "
                + ", ".join(f"{key}={value}" for key, value in self.correlation_context.items())
            )
        if self.aws.environment == "production":
            st.warning(
                f"Destino de PRODUÇÃO: conta {self.aws.account_id}, região {self.aws.region}. "
                "A execução efetiva exige confirmação explícita digitada."
            )
        with st.form(f"flowops:execute-form:{book.id}:{version}"):
            values = self._parameter_inputs(book)
            dry_run = st.checkbox("Simulação do FlowOps", value=True)
            reason = st.text_input("Motivo / referência da mudança")
            production_word = ""
            production_account = ""
            if self.aws.environment == "production":
                production_word = st.text_input(
                    "Digite PRODUCTION para executar efetivamente em produção"
                )
                production_account = st.text_input("Digite os 12 dígitos da conta AWS de destino")
            submitted = st.form_submit_button("Enviar execução", type="primary")
        if any(node.action == "core.approval" for node in book.nodes):
            st.info(
                "Com a simulação do FlowOps marcada, a aprovação é simulada, sem pendência. Desmarcada, a execução pausa em Aprovações. No modo de demonstração, isso afeta somente dados fictícios locais."
            )
        if submitted:
            if self.aws.environment == "production" and not dry_run:
                if production_word != "PRODUCTION" or production_account != self.aws.account_id:
                    raise WorkflowValidationError(
                        "A execução efetiva em produção exige PRODUCTION e o ID exato da conta de destino."
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
            st.success(f"Execução {execution.id} enviada para processamento em segundo plano.")
        last = st.session_state.get("flowops:last_execution")
        if isinstance(last, str):
            try:
                execution = self.runtime.engine.store.get(last)
                st.caption(f"Estado da última execução enviada: {display(execution.status.value)}")
                render_live_execution(self, execution.id)
            except FlowOpsError:
                pass

    def _executions(self) -> None:
        import streamlit as st

        st.header("Histórico de execuções")
        executions = self._visible_executions(2000)
        users = sorted({execution.actor.id for execution in executions})
        environments = sorted({execution.aws_context.environment for execution in executions})
        runbooks = sorted({execution.snapshot.name for execution in executions})
        accounts = sorted({execution.aws_context.account_id for execution in executions})
        # One responsive grid keeps subsequent rows on the same alignment tracks.
        filters = st.columns(7)
        status_filter = filters[0].selectbox(
            "Estado",
            ["ALL"] + [status.value for status in Status],
            format_func=display,
            key="flowops:history-status",
        )
        user_filter = filters[1].selectbox(
            "Usuário",
            ["ALL"] + users,
            format_func=lambda value: "Todos" if value == "ALL" else value,
            key="flowops:history-user",
        )
        environment_filter = filters[2].selectbox(
            "Ambiente",
            ["ALL"] + environments,
            format_func=display,
            key="flowops:history-environment",
        )
        account_filter = filters[3].selectbox(
            "Conta AWS",
            ["ALL"] + accounts,
            format_func=lambda value: "Todas" if value == "ALL" else value,
            key="flowops:history-account",
        )
        runbook_filter = filters[4].selectbox(
            "Procedimento",
            ["ALL"] + runbooks,
            format_func=lambda value: "Todos" if value == "ALL" else value,
            key="flowops:history-runbook",
        )
        date_from = filters[5].date_input(
            "De", value=None, format="DD/MM/YYYY", key="flowops:history-from"
        )
        date_to = filters[6].date_input(
            "Até", value=None, format="DD/MM/YYYY", key="flowops:history-to"
        )

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
        render_summary_table(presentation_rows(rows), width="stretch", hide_index=True)
        if not executions:
            return
        selected_id = st.selectbox(
            "Detalhes da execução",
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
        render_live_execution(self, execution.id)

        st.subheader("Execuções das etapas")
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
        render_summary_table(presentation_rows(node_rows), width="stretch", hide_index=True)
        with st.expander("Detalhes técnicos das etapas", expanded=False):
            st.json(node_details, expanded=False)
        columns = st.columns(2)
        if execution.status in {Status.PENDING, Status.RUNNING, Status.WAITING_APPROVAL}:
            if columns[0].button("Cancelar", key=f"flowops:cancel:{execution.id}"):
                self.runtime.engine.cancel(execution.id, self.user)
                st.rerun()
        if execution.status in {Status.SUCCESS, Status.FAILED, Status.CANCELLED}:
            production_word = ""
            production_account = ""
            if execution.aws_context.environment == "production" and not execution.dry_run:
                st.warning(
                    f"Nova execução efetiva em produção: conta {execution.aws_context.account_id}, região {execution.aws_context.region}."
                )
                production_word = st.text_input(
                    "Digite PRODUCTION para executar novamente",
                    key=f"flowops:rerun-word:{execution.id}",
                )
                production_account = st.text_input(
                    "Digite a conta AWS de destino para executar novamente",
                    key=f"flowops:rerun-account:{execution.id}",
                )
            if columns[1].button("Executar novamente", key=f"flowops:rerun:{execution.id}"):
                if execution.aws_context.environment == "production" and not execution.dry_run:
                    if (
                        production_word != "PRODUCTION"
                        or production_account != execution.aws_context.account_id
                    ):
                        raise WorkflowValidationError(
                            "A nova execução efetiva em produção exige PRODUCTION e o ID exato da conta de destino."
                        )
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
