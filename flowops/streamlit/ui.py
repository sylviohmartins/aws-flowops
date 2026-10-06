"""Streamlit presentation layer. Durable changes happen only on explicit submissions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from flowops.application import FlowOpsRuntime
from flowops.core.graph import LOGIC_REQUIRED, validate_graph
from flowops.core.policies import permissions, require
from flowops.core.serialization import clone_runbook, export_runbook, import_runbook
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import (
    AWSContext,
    Edge,
    Identity,
    Node,
    Parameter,
    Runbook,
    Status,
    new_id,
)
from flowops.persistence.repository import digest
from flowops.providers.aws.catalog_store import DynamoRunbookCatalog
from flowops.providers.aws.resources import discovery_services, explore, resource_choices
from flowops.streamlit.authoring import pending_buffers, require_applied_buffers
from flowops.streamlit.browser_catalog import local_copy, local_records
from flowops.streamlit.canvas import duplicate_node, workflow_canvas
from flowops.streamlit.flow_journey import render_connections, render_guided_step
from flowops.streamlit.graph_layout import LayoutUndo, organize_workflow
from flowops.streamlit.localization import (
    action_label,
    display,
    field_label,
    presentation_rows,
    render_error,
    render_summary_table,
)
from flowops.streamlit.navigation import AREAS, PAGE_LABELS, navigation_pages
from flowops.streamlit.node_editor import dismiss_node, initial_config, render_node_dialog
from flowops.templates import TEMPLATES

ExportFormat = Literal["yaml", "json"]
FailurePolicy = Literal["STOP", "CONTINUE", "RETRY", "FAIL_BRANCH", "MANUAL_INTERVENTION"]
FAILURE_POLICIES: list[FailurePolicy] = [
    "STOP",
    "CONTINUE",
    "RETRY",
    "FAIL_BRANCH",
    "MANUAL_INTERVENTION",
]
NAVIGATION = [
    "Dashboard",
    "Runbooks",
    "Editor",
    "Execute",
    "Executions",
    "Approvals",
    "Audit",
    "Resources",
    "Catalog",
    "Guide",
]


class FlowOpsUI:
    """Thin UI over the application/runtime services."""

    def __init__(self, user: Identity, aws_context: AWSContext, runtime: FlowOpsRuntime):
        self.user = user
        self.aws = aws_context
        self.runtime = runtime
        self.repository = runtime.repository

    def render(self) -> None:
        import streamlit as st

        next_page = st.session_state.pop("flowops:next-page", None)
        if next_page in NAVIGATION:
            st.session_state["flowops:navigation"] = next_page
            area = st.session_state.get("flowops:navigation-area", "Todas as áreas")
            if next_page not in navigation_pages(area):
                st.session_state["flowops:navigation-area"] = "Todas as áreas"
        navigation = st.sidebar.container(key="flowops-navigation")
        area = navigation.selectbox(
            "Área de trabalho",
            list(AREAS),
            key="flowops:navigation-area",
            help="Filtre o menu pelo que deseja fazer. Todas as áreas mantém cada página disponível.",
        )
        pages = navigation_pages(area)
        if st.session_state.get("flowops:navigation", "Dashboard") not in pages:
            st.session_state["flowops:navigation"] = pages[0]
        page = navigation.radio(
            "Navegação", pages, key="flowops:navigation", format_func=PAGE_LABELS.get
        )
        navigation.caption(self.user.display_name or self.user.id)
        navigation.caption(
            "Perfis de acesso: " + ", ".join(display(role) for role in self.user.roles)
        )
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
                "Catalog": self._catalog_page,
                "Guide": self._guide,
            }[page]()
        except (FlowOpsError, ValueError) as exc:
            render_error(exc)

    def _guide(self) -> None:
        import streamlit as st

        guide = Path(__file__).with_name("operator_guide.md").read_text(encoding="utf-8")
        title, _, body = guide.partition("\n")
        st.header(title.removeprefix("# "))
        st.markdown(body.replace("\n## ", "\n### "))

    def _catalog_page(self) -> None:
        from flowops.streamlit.action_catalog import render_catalog

        render_catalog(self)

    def _granted(self, permission: str, book: Runbook | None = None) -> bool:
        try:
            require(self.user, permission, book)
            return True
        except FlowOpsError:
            return False

    def _catalog(self) -> DynamoRunbookCatalog | None:
        if self.aws.mode == "demo" or not hasattr(self.runtime.backend, "client_for_host"):
            return None
        try:
            return DynamoRunbookCatalog(self.runtime.backend, self.aws)
        except ValueError:
            return None

    def _browser_key(self) -> str:
        return digest({"account_id": self.aws.account_id, "user_id": self.user.id})[:24]

    def _sync_catalog(self, book: Runbook) -> str:
        catalog = self._catalog()
        if catalog is None:
            return "demo"
        result = catalog.save(book)
        if result.mode == "fallback":
            # Browser storage is a recovery copy only; Repository remains the source of
            # durable drafts/executions and never depends on a browser being open.
            local_records(
                key=self._browser_key(),
                command="save",
                record=local_copy(book),
            )
        return result.mode

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
            raise WorkflowValidationError(f"{label} deve conter JSON válido.") from exc
        if not isinstance(parsed, dict):
            raise WorkflowValidationError(f"{label} deve ser um objeto JSON.")
        return parsed

    def _selected_id(self) -> str | None:
        import streamlit as st

        selected = st.session_state.get("flowops:selected_runbook")
        books = self._visible_runbooks()
        ids = {book.id for book in books}
        if selected not in ids:
            selected = next(iter(ids), None)
            st.session_state["flowops:selected_runbook"] = selected
        return cast(str | None, selected)

    def _select_runbook(
        self,
        *,
        label: str = "Procedimento",
        published_only: bool = False,
    ) -> Runbook | None:
        import streamlit as st

        books = self._visible_runbooks()
        if published_only:
            books = [book for book in books if self.repository.versions(book.id)]
        if not books:
            st.info("Nenhum procedimento disponível.")
            return None
        selected_id = self._selected_id()
        valid_ids = [book.id for book in books]
        if selected_id not in valid_ids:
            selected_id = valid_ids[0]
        labels = {book.id: f"{book.name} · {book.team}" for book in books}
        widget_key = f"flowops:select:{label}:{published_only}"
        # Programmatic navigation (create/import/duplicate/restore) updates the
        # canonical selection. Keep the persistent widget in sync before it is
        # instantiated; otherwise Streamlit restores its stale previous value.
        if st.session_state.get(widget_key) != selected_id:
            st.session_state[widget_key] = selected_id

        def select_current() -> None:
            value = st.session_state.get(widget_key)
            if value in valid_ids:
                st.session_state["flowops:selected_runbook"] = value

        chosen = st.selectbox(
            label,
            valid_ids,
            index=valid_ids.index(selected_id),
            format_func=lambda value: labels[value],
            key=widget_key,
            on_change=select_current,
        )
        st.session_state["flowops:selected_runbook"] = chosen
        return next(book for book in books if book.id == chosen)

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
        st.subheader("Execuções recentes")
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
        render_summary_table(presentation_rows(rows), width="stretch", hide_index=True)

    def _runbooks(self) -> None:
        import streamlit as st

        st.header("Procedimentos")
        can_edit = self._granted("runbook.edit")
        query = st.text_input("Buscar", key="flowops:runbook-search")
        books = self._visible_runbooks(query)
        browser_key = self._browser_key()
        browser_books = local_records(key=browser_key) if self.aws.mode in {"local", "aws"} else []
        if browser_books:
            with st.expander(f"Cópias neste navegador ({len(browser_books)})", expanded=False):
                st.caption(
                    "Estas cópias pertencem somente a este navegador e endereço do site. Permanecem após reabrir a aba ou o navegador, mas não após limpar os dados do site ou trocar de dispositivo."
                )
                local_index = st.selectbox(
                    "Cópia local",
                    range(len(browser_books)),
                    format_func=lambda index: (
                        f"{browser_books[index].get('name', 'Sem nome')} · "
                        f"v{browser_books[index].get('version', 0)}"
                    ),
                    key="flowops:browser-copy-select",
                )
                if can_edit and st.button(
                    "Restaurar cópia local como novo rascunho", key="flowops:browser-copy-restore"
                ):
                    raw = browser_books[local_index].get("body")
                    if not isinstance(raw, dict):
                        raise WorkflowValidationError(
                            "A cópia do navegador contém uma definição inválida do procedimento."
                        )
                    restored = clone_runbook(
                        Runbook.model_validate(raw), owner=self.user.id, suffix="Cópia"
                    )
                    restored.name = f"{restored.name} (cópia do navegador)"[:160]
                    self.repository.save_draft(restored, self.user.id)
                    self._sync_catalog(restored)
                    st.session_state["flowops:selected_runbook"] = restored.id
                    st.success("Cópia do navegador restaurada como novo rascunho.")
                    st.rerun()
        if can_edit:
            from flowops.streamlit.goal_wizard import render_goal_wizard

            render_goal_wizard(self)
            with st.expander("Criar a partir de um modelo", expanded=not books):
                template_id = st.selectbox(
                    "Modelo",
                    list(TEMPLATES),
                    format_func=lambda key: display(TEMPLATES[key].name),
                    key="flowops:template",
                )
                grants = permissions(self.user)
                if "*" in grants:
                    team = st.text_input(
                        "Equipe",
                        value=self.user.teams[0] if self.user.teams else "default",
                        key="flowops:create-team",
                    )
                else:
                    allowed_teams = self.user.teams or ["default"]
                    team = st.selectbox("Equipe", allowed_teams, key="flowops:create-team")
                name = st.text_input("Nome do procedimento (opcional)", key="flowops:create-name")
                if st.button("Criar procedimento", type="primary", key="flowops:create-runbook"):
                    template = TEMPLATES[template_id]
                    book = template.create(self.user.id, team.strip() or "default")
                    # Only a newly created template draft gets translated defaults.
                    # Existing user definitions and published snapshots are untouched.
                    book.name = display(book.name)
                    book.description = display(book.description)
                    for node in book.nodes:
                        node.label = display(node.label) if node.label else node.label
                        if node.action == "core.approval" and "message" in node.config:
                            node.config["message"] = display(node.config["message"])
                    for parameter in book.parameters.values():
                        parameter.description = display(parameter.description)
                    if name.strip():
                        book.name = name.strip()[:160]
                    self.repository.save_draft(book, self.user.id)
                    self._sync_catalog(book)
                    st.session_state["flowops:selected_runbook"] = book.id
                    st.success("Procedimento criado como rascunho.")
                    st.rerun()
        if not books:
            st.info("Nenhum procedimento corresponde à busca.")
            return
        labels = {book.id: f"{book.name} · {book.team}" for book in books}
        selected = st.selectbox(
            "Procedimentos salvos",
            [book.id for book in books],
            format_func=lambda value: labels[value],
            key="flowops:runbook-list",
        )
        st.session_state["flowops:selected_runbook"] = selected
        book, revision = self.repository.get_draft(selected)
        if can_edit and st.button(
            "Salvar cópia deste procedimento no navegador", key="flowops:browser-copy-save"
        ):
            local_records(key=browser_key, command="save", record=local_copy(book))
            st.success(
                "Cópia salva no navegador. Ela não substitui o histórico de execuções no servidor."
            )
            st.rerun()
        versions = self.repository.versions(book.id)
        st.caption(
            f"Revisão do rascunho {revision} · Versões publicadas: "
            + (", ".join(f"v{version}" for version in versions) if versions else "nenhuma")
        )
        st.write(display(book.description) if book.description else "Sem descrição.")
        st.code(book.id, language=None)
        export_format = cast(
            ExportFormat,
            st.radio(
                "Formato de exportação",
                ["yaml", "json"],
                horizontal=True,
                key="flowops:export-format",
            ),
        )
        st.download_button(
            "Exportar",
            export_runbook(book, export_format),
            file_name=f"{book.name.lower().replace(' ', '-')}.{export_format}",
            mime="application/yaml" if export_format == "yaml" else "application/json",
        )
        if not can_edit:
            return
        action_columns = st.columns(3)
        if action_columns[0].button("Duplicar", key="flowops:clone"):
            require(self.user, "runbook.edit", book)
            cloned = clone_runbook(book, owner=self.user.id, suffix="Cópia")
            self.repository.save_draft(cloned, self.user.id)
            self._sync_catalog(cloned)
            st.session_state["flowops:selected_runbook"] = cloned.id
            st.success("Procedimento duplicado.")
            st.rerun()
        if action_columns[1].button("Arquivar", key="flowops:archive"):
            require(self.user, "runbook.edit", book)
            self.repository.archive(book.id, self.user.id)
            st.session_state["flowops:selected_runbook"] = None
            st.rerun()
        if action_columns[2].button("Excluir logicamente", key="flowops:delete"):
            require(self.user, "runbook.edit", book)
            self.repository.archive(book.id, self.user.id, deleted=True)
            st.session_state["flowops:selected_runbook"] = None
            st.rerun()
        uploaded = st.file_uploader("Importar YAML/JSON", type=["yaml", "yml", "json"])
        if uploaded is not None and st.button("Importar como novo rascunho", key="flowops:import"):
            try:
                text = uploaded.getvalue().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkflowValidationError(
                    "O arquivo do procedimento deve conter texto em UTF-8."
                ) from exc
            imported = import_runbook(text, owner=self.user.id)
            grants = permissions(self.user)
            if "*" not in grants and imported.team not in self.user.teams:
                imported.team = self.user.teams[0] if self.user.teams else "default"
            self.repository.save_draft(imported, self.user.id)
            self._sync_catalog(imported)
            st.session_state["flowops:selected_runbook"] = imported.id
            st.success("Procedimento importado.")
            st.rerun()

    @staticmethod
    def _working_key(book: Runbook) -> str:
        return f"flowops:working:{book.id}"

    def _working_draft(self, book: Runbook, revision: int) -> Runbook:
        import streamlit as st

        key = self._working_key(book)
        cached = st.session_state.get(key)
        if isinstance(cached, dict) and cached.get("revision") != revision:
            raise WorkflowValidationError(
                "O rascunho mudou em outra sessão. Suas edições estão preservadas; compare as revisões no editor."
            )
        if not isinstance(cached, dict) or cached.get("revision") != revision:
            st.session_state[key] = {"revision": revision, "body": book.model_dump_json()}
            return book.model_copy(deep=True)
        return Runbook.model_validate_json(cached["body"])

    def _store_working(self, book: Runbook, revision: int) -> None:
        import streamlit as st

        from flowops.streamlit.edit_history import record_edit

        record_edit(st.session_state, book, revision, st.session_state.get(self._working_key(book)))
        st.session_state[self._working_key(book)] = {
            "revision": revision,
            "body": book.model_dump_json(),
        }

    def _editor(self) -> None:
        import streamlit as st

        st.header("Editor visual de procedimentos")
        selected = self._select_runbook(label="Procedimento em edição")
        if selected is None:
            return
        book, revision = self.repository.get_draft(selected.id)
        require(self.user, "runbook.read", book)
        from flowops.streamlit.edit_history import render_history, render_revision_conflict

        if render_revision_conflict(self, book, revision):
            return
        working = self._working_draft(book, revision)
        editable = self._granted("runbook.edit", book)
        # Register the mode before history can rerun; otherwise Streamlit cleans
        # up this widget and silently returns to the default canvas after undo.
        view = st.radio(
            "Visão de edição",
            ["Canvas", "Canvas avançado", "Lista de etapas", "Assistente"],
            index=1,
            horizontal=True,
            key=f"flowops:editor-view:{book.id}",
        )
        render_history(self, working, revision)
        with st.expander("Detalhes do procedimento", expanded=False):
            with st.form(f"flowops:metadata:{book.id}"):
                name = st.text_input("Nome", value=working.name, disabled=not editable)
                description = st.text_area(
                    "Descrição",
                    value=working.description,
                    disabled=not editable,
                    height=80,
                )
                tags = st.text_input(
                    "Marcadores (separados por vírgula)",
                    value=", ".join(working.tags),
                    disabled=not editable,
                )
                environments = st.multiselect(
                    "Ambientes permitidos",
                    ["dev", "staging", "production"],
                    format_func=display,
                    default=working.environments,
                    disabled=not editable,
                )
                metadata_applied = st.form_submit_button("Aplicar detalhes", disabled=not editable)
            if metadata_applied:
                working.name = name.strip() or working.name
                working.description = description
                working.tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
                working.environments = environments or ["dev"]
                self._store_working(working, revision)
                st.rerun()

            from flowops.streamlit.parameter_editor import render_parameter_editor

            render_parameter_editor(self, working, revision)

        with st.expander(
            "Adicionar etapa pelo formulário",
            expanded=st.session_state.get(f"flowops:editor-view:{book.id}", "Canvas avançado")
            != "Canvas avançado",
        ):
            st.subheader("Adicionar etapa")
            st.caption(
                "1. Escolha uma ação · 2. Insira no fluxo · 3. Clique na caixa para configurar · 4. Valide e salve"
            )
            logic = sorted(LOGIC_REQUIRED)
            provider = [metadata.id for metadata in self.runtime.registry.list()]
            requested = st.session_state.pop("flowops:catalog-action", None)
            if requested in provider:
                st.session_state[f"flowops:action-service:{book.id}"] = "All"
                st.session_state[f"flowops:action-search:{book.id}"] = ""
                st.session_state[f"flowops:add-action:{book.id}"] = requested
            filters = st.columns(2)
            service = filters[0].selectbox(
                "Serviço da ação",
                ["All", "core"] + sorted({entry.split(".")[0] for entry in provider}),
                format_func=display,
                key=f"flowops:action-service:{book.id}",
            )
            search = (
                filters[1]
                .text_input("Buscar ação", key=f"flowops:action-search:{book.id}")
                .strip()
                .lower()
            )
            available = [
                entry
                for entry in logic + provider
                if (service == "All" or entry.startswith(service + "."))
                and search in action_label(entry).lower()
            ]
            if not available:
                st.info("Nenhuma ação corresponde aos filtros. Limpe a busca para continuar.")
            action_id = st.selectbox(
                "Ação",
                available,
                format_func=action_label,
                disabled=not editable or not available,
                key=f"flowops:add-action:{book.id}",
            )
            if action_id and action_id not in LOGIC_REQUIRED:
                metadata = self.runtime.registry.get(action_id).metadata
                st.caption(
                    f"Operação {action_id} · risco {display(metadata.risk.value)} · "
                    f"permissões {', '.join(metadata.required_permissions) or 'política do provedor'}"
                )
            if st.button(
                "Inserir antes do fim",
                disabled=not editable or not available,
                key=f"flowops:add-node:{book.id}",
            ):
                end = next((node for node in working.nodes if node.action == "core.end"), None)
                if end is None:
                    raise WorkflowValidationError(
                        "Adicione uma etapa de fim antes de inserir ações."
                    )
                node_id = f"n_{new_id()[:12]}"
                node = Node(
                    id=node_id,
                    action=action_id,
                    label=action_id,
                    config=initial_config(action_id),
                    position=end.position,
                )
                end.position = (end.position[0] + 260, end.position[1])
                incoming = [edge for edge in working.edges if edge.target == end.id]
                working.edges = [edge for edge in working.edges if edge.target != end.id]
                for edge in incoming:
                    edge.target = node_id
                working.edges.extend(incoming)
                working.edges.append(Edge(source=node_id, target=end.id))
                working.nodes.append(node)
                self._store_working(working, revision)
                st.rerun()

        st.subheader("Área do fluxo")
        if view in {"Canvas", "Canvas avançado"}:
            self._layout_tools(working, revision, editable)
        if view == "Canvas":
            canvas_book, canvas_selected = workflow_canvas(
                working, key=f"flowops-canvas-{book.id}", readonly=not editable
            )
        elif view == "Canvas avançado":
            from flowops.streamlit.react_editor import render_react_editor

            st.caption(
                "Edite campos nas caixas e aplique ao rascunho. Conexões de dados preenchem campos; conexões de execução definem a ordem. Desfazer/refazer ficam acima do editor."
            )
            canvas_book, canvas_selected = render_react_editor(self, working, revision)
        else:
            canvas_book, canvas_selected = working, None
            if view == "Lista de etapas":
                render_summary_table(
                    [
                        {
                            "Etapa": node.id,
                            "Nome": display(node.label),
                            "Ação": node.action,
                            "Destinos": ", ".join(
                                f"{edge.target} ({display(edge.branch)})"
                                for edge in working.edges
                                if edge.source == node.id
                            ),
                        }
                        for node in working.nodes
                    ],
                    hide_index=True,
                    width="stretch",
                )
        self._store_working(canvas_book, revision)
        undo_key = f"flowops:layout-undo:{book.id}"
        undo = st.session_state.get(undo_key)
        if isinstance(undo, LayoutUndo) and not undo.matches(canvas_book, revision):
            st.session_state.pop(undo_key, None)
            st.rerun()
        if len(canvas_book.edges) > len(working.edges):
            st.rerun()
        working = canvas_book
        selection_key = f"flowops:node:{book.id}"
        canvas_selection_key = f"flowops:canvas-selection:{book.id}"
        suppress_key = f"flowops:suppress-canvas-selection:{book.id}"
        suppressed = st.session_state.pop(suppress_key, None)
        if suppressed is not None and canvas_selected == suppressed:
            # Ignore the single stale selected_id emitted while the canvas
            # widget identity is reset after closing a node dialog.
            canvas_selected = None
        pending = st.session_state.pop(f"flowops:pending-node:{book.id}", None)
        if pending is not None:
            st.session_state[selection_key] = pending
        elif canvas_selected and canvas_selected != st.session_state.get(canvas_selection_key):
            st.session_state[selection_key] = canvas_selected
            st.session_state[f"flowops:node-dialog:{book.id}"] = canvas_selected
        st.session_state[canvas_selection_key] = canvas_selected
        if st.session_state.get(selection_key) not in {node.id for node in working.nodes}:
            st.session_state.pop(selection_key, None)
        st.caption(
            "Clique em uma caixa para editar. Arraste as alças para conectar etapas. "
            "Clique com o botão direito em uma conexão para definir seu ramo ou desconectar."
        )
        render_connections(self, working, revision)

        if working.nodes:
            selected_node_id = st.selectbox(
                "Propriedades da etapa",
                [node.id for node in working.nodes],
                format_func=lambda node_id: next(
                    f"{node.label or node.id} · {node.action}"
                    for node in working.nodes
                    if node.id == node_id
                ),
                key=f"flowops:node:{book.id}",
            )
            node = next(node for node in working.nodes if node.id == selected_node_id)
            if view == "Assistente":
                render_guided_step(self, working, node.id, revision)
            elif st.session_state.get(f"flowops:node-dialog:{book.id}") == node.id:
                render_node_dialog(self, working, node, revision)
            else:
                if st.button("Editar etapa selecionada", key=f"flowops:edit-selected:{book.id}"):
                    st.session_state[f"flowops:node-dialog:{book.id}"] = node.id
                    st.rerun()
                with st.expander("Propriedades avançadas na página", expanded=False):
                    self._node_form(working, node, revision, editable)

        dirty = digest(working.model_dump()) != digest(book.model_dump())
        from flowops.streamlit.authoring_review import render_review

        render_review(self, working, revision)
        pending_edits = pending_buffers(working, st.session_state)
        if pending_edits:
            st.warning(
                "Campos ainda não aplicados: "
                + ", ".join(pending_edits)
                + ". Aplique a configuração antes de salvar ou publicar."
            )
        if dirty:
            st.warning("As alterações não salvas permanecem somente nesta sessão do editor.")
        columns = st.columns(3)
        validation_key = f"flowops:validated:{book.id}"
        if columns[0].button("Validar", key=f"flowops:validate:{book.id}"):
            st.session_state.pop(validation_key, None)
            validate_graph(working, self.runtime.registry)
            st.session_state[validation_key] = digest(working.model_dump())
        if st.session_state.get(validation_key) == digest(working.model_dump()):
            st.success(f"Fluxo válido: {len(working.nodes)} etapas.")
        if columns[1].button(
            "Salvar rascunho",
            disabled=not editable or bool(pending_edits),
            key=f"flowops:save:{book.id}",
        ):
            require(self.user, "runbook.edit", working)
            require_applied_buffers(working, st.session_state)
            validate_graph(working, self.runtime.registry)
            new_revision = self.repository.save_draft(working, self.user.id, revision)
            catalog_mode = self._sync_catalog(working)
            st.session_state.pop(self._working_key(book), None)
            st.success(f"Revisão do rascunho {new_revision} salva ({display(catalog_mode)}).")
            st.rerun()
        can_publish = self._granted("runbook.publish", book)
        if columns[2].button(
            "Publicar versão",
            disabled=not can_publish or dirty or bool(pending_edits),
            key=f"flowops:publish:{book.id}",
        ):
            require(self.user, "runbook.publish", book)
            require_applied_buffers(working, st.session_state)
            validate_graph(book, self.runtime.registry)
            published = self.repository.publish(book.id, self.user.id, revision)
            catalog_mode = self._sync_catalog(published)
            st.success(f"Publicada v{published.version} ({display(catalog_mode)}).")
            st.rerun()

    def _layout_tools(self, working: Runbook, revision: int, editable: bool) -> None:
        import streamlit as st

        undo_key = f"flowops:layout-undo:{working.id}"
        notice_key = f"flowops:layout-notice:{working.id}"
        undo = st.session_state.get(undo_key)
        if isinstance(undo, LayoutUndo) and not undo.matches(working, revision):
            st.session_state.pop(undo_key, None)
            undo = None
        columns = st.columns(2)
        if columns[0].button(
            "Organizar fluxo",
            disabled=not editable or len(working.nodes) < 2,
            key=f"flowops:organize:{working.id}",
            help="Alinha as etapas da esquerda para a direita, sem alterar suas conexões.",
        ):
            require(self.user, "runbook.edit", working)
            organized, snapshot = organize_workflow(working, revision)
            if snapshot is not None:
                st.session_state.pop(notice_key, None)
                st.session_state[undo_key] = snapshot
                self._store_working(organized, revision)
                st.session_state[f"flowops:pending-node:{working.id}"] = st.session_state.get(
                    f"flowops:node:{working.id}"
                )
                st.rerun()
            st.session_state[notice_key] = digest(working.model_dump())
        if columns[1].button(
            "Desfazer organização",
            disabled=not editable or not isinstance(undo, LayoutUndo),
            key=f"flowops:undo-layout:{working.id}",
        ):
            require(self.user, "runbook.edit", working)
            if isinstance(undo, LayoutUndo):
                st.session_state.pop(notice_key, None)
                self._store_working(undo.restore(working, revision), revision)
                st.session_state.pop(undo_key, None)
                st.session_state[f"flowops:pending-node:{working.id}"] = st.session_state.get(
                    f"flowops:node:{working.id}"
                )
                st.rerun()
        if st.session_state.get(notice_key) == digest(working.model_dump()):
            st.info("O fluxo já está organizado.")
        st.caption(
            "Organizar altera apenas as posições nesta sessão. Use Salvar rascunho para gravar. "
            "Desfazer vale até salvar, arrastar caixas ou alterar etapas/conexões; "
            "edições nos campos são preservadas."
        )

    def _node_tools(self, working: Runbook, node: Node, revision: int) -> None:
        """Optional contextual tools supplied by the operations workspace."""

    def _node_form(
        self,
        working: Runbook,
        node: Node,
        revision: int,
        editable: bool,
        *,
        include_config: bool = True,
    ) -> None:
        import streamlit as st

        with st.form(f"flowops:node-form:{working.id}:{node.id}"):
            label = st.text_input("Nome da etapa", value=node.label, disabled=not editable)
            enabled = st.checkbox("Habilitada", value=node.enabled, disabled=not editable)
            failure = cast(
                FailurePolicy,
                st.selectbox(
                    "Tratamento de falha",
                    FAILURE_POLICIES,
                    format_func=display,
                    index=FAILURE_POLICIES.index(node.failure_policy),
                    disabled=not editable,
                ),
            )
            retry_attempts = st.number_input(
                "Número máximo de tentativas",
                min_value=1,
                max_value=5,
                value=node.retry.max_attempts,
                step=1,
                disabled=not editable,
            )
            retry_backoff = st.number_input(
                "Intervalo entre tentativas (segundos)",
                min_value=0.0,
                max_value=10.0,
                value=float(node.retry.backoff_seconds),
                step=0.1,
                disabled=not editable,
            )
            retry_codes = st.text_input(
                "Códigos para nova tentativa (separados por vírgula)",
                value=", ".join(node.retry.retry_codes),
                disabled=not editable,
            )
            config_text = (
                st.text_area(
                    "Configuração (JSON)",
                    value=json.dumps(node.config, indent=2, ensure_ascii=False),
                    height=260,
                    disabled=not editable,
                )
                if include_config
                else None
            )
            node_applied = st.form_submit_button(
                "Aplicar propriedades da etapa",
                disabled=not editable,
            )
        if node_applied:
            require(self.user, "runbook.edit", working)
            parsed = (
                self._json_object(config_text, label="Configuração da etapa")
                if config_text is not None
                else node.config
            )
            node.label = label[:120]
            node.enabled = enabled
            node.failure_policy = failure
            node.retry.max_attempts = int(retry_attempts)
            node.retry.backoff_seconds = float(retry_backoff)
            node.retry.retry_codes = [
                code.strip() for code in retry_codes.split(",") if code.strip()
            ]
            node.config = parsed
            self._store_working(working, revision)
            st.rerun()
        if editable and node.action not in {"core.start", "core.end"}:
            if st.button(
                "Duplicar etapa selecionada", key=f"flowops:duplicate:{working.id}:{node.id}"
            ):
                working, copied_id = duplicate_node(working, node.id)
                self._store_working(working, revision)
                st.session_state[f"flowops:pending-node:{working.id}"] = copied_id
                if st.session_state.get(f"flowops:node-dialog:{working.id}") == node.id:
                    st.session_state[f"flowops:node-dialog:{working.id}"] = copied_id
                st.rerun()
            if st.button(
                "Remover etapa selecionada",
                key=f"flowops:remove:{working.id}:{node.id}",
            ):
                parents = [edge.source for edge in working.edges if edge.target == node.id]
                children = [edge.target for edge in working.edges if edge.source == node.id]
                working.nodes = [entry for entry in working.nodes if entry.id != node.id]
                working.edges = [
                    edge
                    for edge in working.edges
                    if edge.source != node.id and edge.target != node.id
                ]
                for parent in parents:
                    for child in children:
                        if parent != child:
                            working.edges.append(Edge(source=parent, target=child))
                self._store_working(working, revision)
                dismiss_node(working.id)
                st.rerun()

    def _parameter_inputs(self, book: Runbook) -> dict[str, tuple[Parameter, Any]]:
        import streamlit as st

        values: dict[str, tuple[Parameter, Any]] = {}
        for name, spec in book.parameters.items():
            label = f"{field_label(name)}{' *' if spec.required else ''}"
            default = spec.default
            if spec.type == "boolean":
                value: Any = st.checkbox(
                    label,
                    value=bool(default) if default is not None else False,
                )
            elif spec.type == "integer":
                value = st.number_input(label, value=int(default or 0), step=1)
            elif spec.type == "number":
                value = st.number_input(label, value=float(default or 0.0))
            elif spec.type in {"array", "object"}:
                empty: list[Any] | dict[str, Any] = [] if spec.type == "array" else {}
                value = st.text_area(
                    label,
                    value=json.dumps(default if default is not None else empty),
                )
            else:
                value = st.text_input(label, value="" if default is None else str(default))
            if spec.description:
                st.caption(display(spec.description))
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
                    raise WorkflowValidationError(
                        f"Parâmetro {name} deve conter JSON válido."
                    ) from exc
            if spec.type == "string" and not spec.required and value == "":
                value = None
            supplied[name] = value
        return supplied

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
            )
            self.runtime.worker.enqueue(execution.id)
            st.session_state["flowops:last_execution"] = execution.id
            st.success(f"Execução {execution.id} enviada para processamento em segundo plano.")
        last = st.session_state.get("flowops:last_execution")
        if isinstance(last, str):
            try:
                execution = self.runtime.engine.store.get(last)
                st.caption(f"Estado da última execução enviada: {display(execution.status.value)}")
            except FlowOpsError:
                pass

    def _executions(self) -> None:
        import streamlit as st

        st.header("Histórico de execuções")
        executions = self._visible_executions(1000)
        status_filter = st.selectbox(
            "Estado",
            ["ALL"] + [status.value for status in Status],
            format_func=display,
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
                "dry_run": execution.dry_run,
                "status": execution.status.value,
                "error": execution.error,
            },
            expanded=False,
        )
        st.subheader("Execuções das etapas")
        st.json(self.runtime.engine.store.nodes(execution.id), expanded=False)
        columns = st.columns(2)
        if execution.status in {Status.PENDING, Status.RUNNING, Status.WAITING_APPROVAL}:
            if columns[0].button("Cancelar", key=f"flowops:cancel:{execution.id}"):
                self.runtime.engine.cancel(execution.id, self.user)
                st.rerun()
        if execution.status in {Status.SUCCESS, Status.FAILED, Status.CANCELLED}:
            if columns[1].button("Executar novamente", key=f"flowops:rerun:{execution.id}"):
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

        st.header("Aprovações")
        approvals: list[dict[str, Any]] = []
        for approval in self.runtime.engine.store.pending_approvals():
            execution = self.runtime.engine.store.get(approval["execution_id"])
            permission = f"runbook.approve.{execution.aws_context.environment}"
            if self._granted(permission, execution.snapshot):
                approvals.append(approval)
        if not approvals:
            st.info("Nenhuma aprovação pendente.")
            st.caption(
                "A simulação do FlowOps também simula a aprovação. Para testar uma aprovação manual, use execução efetiva no modo de demonstração ou no laboratório local. Na AWS real, respeite as autorizações do ambiente."
            )
            return
        for approval in approvals:
            body = approval["body"]
            execution = self.runtime.engine.store.get(approval["execution_id"])
            self_approval = (
                self.runtime.engine.policy.two_person and execution.actor.id == self.user.id
            )
            st.subheader(f"{display(body.get('environment', ''))} · {approval['execution_id']}")
            st.caption(
                f"Solicitante: {execution.actor.id} · etapa: {approval['node_id']} · aguardando decisão"
            )
            if self_approval:
                st.warning(
                    "Esta política exige outra pessoa: o solicitante não pode decidir a própria execução."
                )
            st.json(body, expanded=False)
            reason = st.text_input(
                "Motivo da decisão",
                key=f"flowops:approval-reason:{approval['execution_id']}:{approval['node_id']}",
            )
            columns = st.columns(2)
            if columns[0].button(
                "Aprovar",
                type="primary",
                disabled=self_approval,
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
                "Rejeitar",
                disabled=self_approval,
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

        st.header("Auditoria")
        events = self.repository.events(limit=1000)
        visible_executions = {execution.id for execution in self._visible_executions(2000)}
        visible_books = {book.id for book in self._visible_runbooks()}
        events = [
            event
            for event in events
            if (event["execution_id"] and event["execution_id"] in visible_executions)
            or (not event["execution_id"] and event["body"].get("runbook_id") in visible_books)
        ]
        event_filter = st.text_input("Filtrar evento", key="flowops:audit-filter").strip().upper()
        if event_filter:
            events = [event for event in events if event_filter in event["event"].upper()]
        rows = [
            {
                "when": event["created_at"],
                "who": event["actor"],
                "what": event["event"],
                "execution": event["execution_id"],
                "where": " / ".join(
                    str(event["body"].get(key, "")) for key in ("environment", "account", "region")
                ).strip(" /"),
                "why": event["body"].get("reason", ""),
                "result": event["body"].get("result", ""),
            }
            for event in events
        ]
        render_summary_table(presentation_rows(rows), width="stretch", hide_index=True)
        if events:
            event_id = st.selectbox(
                "Detalhes do evento",
                [event["id"] for event in events],
                key="flowops:audit-detail",
            )
            event = next(entry for entry in events if entry["id"] == event_id)
            st.json(event, expanded=False)

    def _resources(self) -> None:
        import streamlit as st

        st.header("Explorador de recursos AWS")
        if not self._granted("aws.read"):
            st.warning("Seu perfil não possui a permissão aws.read.")
            return
        services = discovery_services()
        service = st.selectbox(
            "Serviço",
            services,
            index=services.index("dynamodb") if "dynamodb" in services else 0,
            key="flowops:resource-service",
        )
        result_key = f"flowops:resource-result:{service}"
        if st.button("Buscar recursos", key="flowops:resources-discover"):
            result = explore(self.runtime.registry, self.user, self.aws, service)
            st.session_state[result_key] = result
        result = st.session_state.get(result_key)
        if result is not None:
            st.json(result, expanded=False)
            choices = resource_choices(service, result)
            if choices:
                st.caption(
                    f"{len(choices)} recurso(s) encontrado(s). Recursos são listados sem alterações."
                )
        st.caption(
            "A busca de recursos é somente leitura e ocorre apenas ao clicar em Buscar recursos."
        )
