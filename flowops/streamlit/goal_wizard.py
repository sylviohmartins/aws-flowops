"""An explicit, resumable creation journey; building a definition never calls AWS."""

from typing import Any

from flowops.core.expressions import path_parts
from flowops.core.graph import validate_graph
from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Edge, Node, Parameter, Runbook
from flowops.providers.aws.resources import explore, resource_choices
from flowops.streamlit.localization import render_error
from flowops.templates import dynamodb_query_lambda

STEPS = ["Objetivo", "Consulta", "Transformação", "Destino e aprovação", "Revisão"]
REQUIRED = {
    0: ("name",),
    1: ("table", "partition", "payment"),
    2: ("id_field", "status_field"),
    3: ("function", "approval"),
}
DEFAULTS: dict[str, Any] = {
    "name": "",
    "table": "",
    "partition": "paymentId",
    "payment": "",
    "id_field": "paymentId",
    "status_field": "status",
    "filter": False,
    "filter_value": "PROCESSING",
    "function": "",
    "approval": "Confira os registros e a função de destino antes de autorizar o envio.",
    "limit": 30,
    "invocation": "RequestResponse",
}


def validate_step(values: dict[str, Any], step: int) -> None:
    if any(not str(values.get(name, "")).strip() for name in REQUIRED.get(step, ())):
        raise WorkflowValidationError("Preencha os campos desta etapa antes de continuar.")
    if any("{{" in str(values.get(name, "")) for name in REQUIRED.get(step, ())):
        raise WorkflowValidationError(
            "Informe valores comuns; o assistente cria os vínculos automaticamente."
        )
    if step == 2:
        for name in ("id_field", "status_field"):
            if len(path_parts("item." + values[name])) != 2:
                raise WorkflowValidationError(
                    "Use um nome de atributo simples. Campos especiais continuam disponíveis no editor avançado."
                )


def build_goal(values: dict[str, Any], owner: str, team: str) -> Runbook:
    for step in REQUIRED:
        validate_step(values, step)
    if type(values["limit"]) is not int or not 1 <= values["limit"] <= 100:
        raise WorkflowValidationError("O limite por consulta deve estar entre 1 e 100.")
    if values["invocation"] not in {"RequestResponse", "Event"}:
        raise WorkflowValidationError("Escolha uma modalidade de invocação disponível.")
    book = dynamodb_query_lambda(owner, team)
    book.name = values["name"].strip()
    book.environments = ["dev"]
    book.parameters = {
        "table_name": Parameter(
            default=values["table"], description="Tabela DynamoDB no contexto selecionado"
        ),
        "payment_id": Parameter(
            default=values["payment"], description="Valor textual da chave de partição da consulta"
        ),
        "function_name": Parameter(
            default=values["function"], description="Nome ou ARN da função no contexto selecionado"
        ),
    }
    nodes = {node.id: node for node in book.nodes}
    nodes["query"].config["ExpressionAttributeNames"] = {"#pk": values["partition"]}
    nodes["query"].config["Limit"] = values["limit"]
    nodes["prepare_event"].config["template"] = {
        "payment_id": "{{ item." + values["id_field"] + ".S }}",
        "status": "{{ item." + values["status_field"] + ".S }}",
    }
    nodes["approve"].config["message"] = values["approval"]
    nodes["invoke"].config["InvocationType"] = values["invocation"]
    if values.get("filter"):
        filtered = Node(
            id="filter",
            action="core.filter",
            label="Filtrar registros",
            position=(400, 180),
            config={
                "items": "{{ nodes.query.output.Items }}",
                "path": values["status_field"] + ".S",
                "operator": "eq",
                "value": values["filter_value"],
            },
        )
        book.nodes.insert(2, filtered)
        book.edges = [
            edge
            for edge in book.edges
            if not (edge.source == "query" and edge.target == "prepare_event")
        ]
        book.edges.extend(
            [Edge(source="query", target="filter"), Edge(source="filter", target="prepare_event")]
        )
        nodes["prepare_event"].config["items"] = "{{ nodes.filter.output.items }}"
    validate_graph(book)
    return book


def render_goal_wizard(ui: Any) -> None:
    import streamlit as st

    key = "flowops:goal-wizard"
    state = st.session_state.setdefault(key, {"step": 0, "values": dict(DEFAULTS)})
    step, values = state["step"], state["values"]
    resources = state.setdefault("resources", {})
    with st.expander("Criar por objetivo: consultar DynamoDB e enviar para Lambda", expanded=False):
        st.progress((step + 1) / len(STEPS), text=f"{step + 1}/{len(STEPS)} · {STEPS[step]}")
        st.caption(
            f"Contexto: {ui.aws.environment} · {ui.aws.account_id} · {ui.aws.region} · {ui.aws.mode}"
        )
        st.info(
            "Este assistente prepara uma consulta por chave textual (S), transforma identificador/status e solicita aprovação antes da Lambda. Índices, outros tipos e estruturas adicionais podem ser configurados depois no editor."
        )
        discovery_service = "dynamodb" if step == 1 else "lambda" if step == 3 else None
        if discovery_service is not None and st.button(
            "Buscar tabelas DynamoDB da conta"
            if discovery_service == "dynamodb"
            else "Buscar funções Lambda da conta",
            key=f"{key}:discover:{discovery_service}",
        ):
            try:
                resources[discovery_service] = resource_choices(
                    discovery_service,
                    explore(
                        ui.runtime.registry,
                        ui.user,
                        ui.aws,
                        discovery_service,
                    ),
                )
            except FlowOpsError as exc:
                render_error(exc)
        with st.form(f"{key}:{step}"):
            updated: dict[str, Any] = {}

            def text(name: str, label: str, help_text: str) -> None:
                updated[name] = st.text_input(label, value=values[name], help=help_text)

            def resource_text(
                name: str,
                label: str,
                help_text: str,
                service: str,
                selector_label: str,
            ) -> None:
                choices = resources.get(service, [])
                if not isinstance(choices, list) or not choices:
                    text(name, label, help_text)
                    return
                options = [""] + [value for value in choices if isinstance(value, str)]
                current = values.get(name, "")
                selected = st.selectbox(
                    selector_label,
                    options,
                    index=options.index(current) if current in options else 0,
                    format_func=lambda value: value or "Informar manualmente",
                )
                if selected:
                    updated[name] = selected
                else:
                    text(name, label, help_text)

            if step == 0:
                text(
                    "name",
                    "Nome do novo fluxo",
                    "Use uma descrição que explique o resultado operacional.",
                )
                teams = ui.user.teams or ["default"]
                updated["team"] = st.selectbox(
                    "Equipe responsável",
                    teams,
                    index=teams.index(values.get("team")) if values.get("team") in teams else 0,
                )
                st.caption(
                    "Será criado um rascunho para Desenvolvimento. Salvar, publicar e executar permanecem ações separadas."
                )
            elif step == 1:
                resource_text(
                    "table",
                    "Tabela a consultar",
                    "Informe a tabela do contexto atual. O nome será um parâmetro reutilizável.",
                    "dynamodb",
                    "Tabela DynamoDB encontrada",
                )
                text(
                    "partition",
                    "Nome da chave de partição",
                    "Query exige igualdade na chave; confirme o nome e o tipo S na estrutura da tabela.",
                )
                text(
                    "payment",
                    "Valor da chave de partição",
                    "Informe o identificador desejado. Ele vira um parâmetro solicitado na execução.",
                )
                updated["limit"] = st.number_input(
                    "Máximo de itens avaliados por requisição",
                    min_value=1,
                    max_value=100,
                    value=values["limit"],
                )
                st.caption(
                    "Query retorna Items; GetItem retorna Item e exige chave completa. Scan faz uma varredura e não é usado por este assistente. O limite não garante a quantidade de resultados e a leitura pode ter custo na AWS. Paginação automática permanece desligada."
                )
            elif step == 2:
                text(
                    "id_field",
                    "Atributo do identificador",
                    "Nome do atributo textual a renomear para payment_id; a interface cria a referência ao item.",
                )
                text(
                    "status_field",
                    "Atributo do status",
                    "Nome do atributo textual a incluir no evento como status.",
                )
                updated["filter"] = st.checkbox(
                    "Filtrar registros pelo status", value=values["filter"]
                )
                text(
                    "filter_value",
                    "Status a manter",
                    "Comparação de igualdade local depois da consulta. Não reduz o custo da leitura DynamoDB.",
                )
                st.json(
                    {"exemplo_fictício": {"payment_id": "12345", "status": "PROCESSING"}},
                    expanded=False,
                )
                st.caption(
                    "Exemplo ilustrativo; não é saída da AWS. Mapear renomeia campos e não converte números ou datas."
                )
            elif step == 3:
                resource_text(
                    "function",
                    "Função Lambda de destino",
                    "Informe o nome ou ARN permitido no contexto. Será um parâmetro reutilizável.",
                    "lambda",
                    "Função Lambda encontrada",
                )
                updated["invocation"] = st.selectbox(
                    "Modalidade de envio",
                    ["RequestResponse", "Event"],
                    index=["RequestResponse", "Event"].index(values["invocation"]),
                    format_func=lambda value: (
                        "Aguardar resposta da função"
                        if value == "RequestResponse"
                        else "Enviar de forma assíncrona"
                    ),
                )
                text(
                    "approval",
                    "O que deve ser conferido na aprovação",
                    "Explique a intenção, o destino e os dados que justificam o envio.",
                )
                st.caption(
                    "Envio assíncrono confirma aceitação, não sucesso interno da função. A aprovação manual não substitui exigências adicionais da política."
                )
            else:
                candidate = build_goal(values, ui.user.id, values["team"])
                st.write(
                    f"{candidate.name}: {values['table']} → transformação → aprovação → {values['function']}"
                )
                st.write("Parâmetros solicitados: tabela, chave de partição e função de destino.")
                st.caption(
                    "Revise os valores antes de criar. Depois use o editor para objetos/listas e a revisão contextual para validar e publicar."
                )
                with st.expander("Ver definição JSON"):
                    st.json(candidate.model_dump(mode="json"), expanded=False)
            back = st.form_submit_button("Voltar", disabled=step == 0)
            forward = st.form_submit_button(
                "Criar rascunho e abrir editor" if step == 4 else "Continuar", type="primary"
            )
        if back or forward:
            state["values"].update(updated)
            try:
                if forward:
                    validate_step(state["values"], step)
                if forward and step == 4:
                    book = build_goal(values, ui.user.id, values["team"])
                    require(ui.user, "runbook.edit", book)
                    validate_graph(book, ui.runtime.registry)
                    ui.repository.save_draft(book, ui.user.id)
                    ui._sync_catalog(book)
                    st.session_state["flowops:selected_runbook"] = book.id
                    st.session_state[f"flowops:editor-view:{book.id}"] = "Assistente"
                    st.session_state[f"flowops:pending-node:{book.id}"] = "query"
                    st.session_state["flowops:next-page"] = "Editor"
                    st.session_state.pop(key, None)
                else:
                    state["step"] += 1 if forward else -1
                st.rerun()
            except FlowOpsError as exc:
                render_error(exc)
