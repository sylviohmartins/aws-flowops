"""Explicit resource discovery and DynamoDB query construction for node properties."""

from __future__ import annotations

from typing import Any

from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.persistence.repository import digest
from flowops.providers.aws.query_builder import key_fields
from flowops.providers.aws.resources import (
    discover_field,
    discovery_rules,
    inspect_resource,
    inspection_rules,
    missing_dependencies,
    read_action,
    sample_dynamodb_fields,
    supporting_discovery_rules,
)
from flowops.streamlit.dynamodb_authoring import build_bound_read, decode_read
from flowops.streamlit.localization import (
    display,
    field_label,
    presentation_rows,
    render_error,
    render_summary_table,
)


def _fingerprint(ui: Any, scope: str, node_id: str) -> str:
    from flowops.persistence.repository import digest

    return digest({"context": ui.aws.model_dump(mode="json"), "scope": scope, "node": node_id})[:20]


def _discovery_signature(ui: Any, rule: Any, current: dict[str, Any]) -> str:
    dependencies = {source: current.get(source) for _, source in rule.request_from}
    return digest(
        {
            "context": ui.aws.model_dump(mode="json"),
            "action": rule.action_id,
            "field": rule.field,
            "dependencies": dependencies,
        }
    )[:20]


def _inspection_signature(ui: Any, rule: Any, current: dict[str, Any], selected: Any) -> str:
    values = dict(current)
    values[rule.field] = selected
    dependencies = {source: values.get(source) for _, source, _ in rule.request_from}
    return digest(
        {
            "context": ui.aws.model_dump(mode="json"),
            "action": rule.action_id,
            "field": rule.field,
            "dependencies": dependencies,
        }
    )[:20]


def _apply_resource(node: Any, field: str, selected: Any) -> None:
    node.config[field] = selected


def _render_dynamodb_query(
    ui: Any,
    book: Any,
    node: Any,
    revision: int,
    table_name: str,
    *,
    key: str,
) -> None:
    import streamlit as st

    describe_key = f"{key}:describe:{digest(table_name)[:12]}"
    if st.button("Carregar estrutura da tabela", key=f"{key}:describe-button"):
        result = read_action(
            ui.runtime.registry,
            ui.user,
            ui.aws,
            "dynamodb.describe_table",
            {"TableName": table_name},
        )
        st.session_state[describe_key] = result.get("Table", result)
    table = st.session_state.get(describe_key)
    if not isinstance(table, dict):
        st.caption(
            "Carregue a estrutura da tabela para gerar uma requisição GetItem ou Query com limite de leitura."
        )
        return
    render_summary_table(
        presentation_rows(
            [
                {"field": field["name"], "type": field["type"], "role": field["key_type"]}
                for field in key_fields(table)
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    indexes = []
    for kind, entries in (
        ("Global", table.get("GlobalSecondaryIndexes", [])),
        ("Local", table.get("LocalSecondaryIndexes", [])),
    ):
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("IndexName"), str):
                continue
            keys = key_fields(table, entry["IndexName"])
            indexes.append(
                {
                    "index": entry["IndexName"],
                    "kind": kind,
                    "keys": ", ".join(
                        f"{field['key_type']}:{field['name']} ({field['type']})" for field in keys
                    ),
                    "projection": entry.get("Projection", {}).get("ProjectionType", "—"),
                }
            )
    if indexes:
        st.caption("Índices disponíveis na tabela")
        render_summary_table(
            presentation_rows(indexes),
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "DynamoDB não possui um schema completo de colunas. Os atributos exibidos acima são "
        "somente os declarados para chaves e índices; outros campos podem variar entre itens."
    )
    sample_key = f"{key}:observed-fields:{digest(table_name)[:12]}"
    if st.button(
        "Amostrar atributos observados (até 10 itens)",
        key=f"{key}:sample-fields",
        help="Executa um Scan somente leitura com Limit=10 e sem paginação automática.",
    ):
        rows, sampled = sample_dynamodb_fields(
            ui.runtime.registry,
            ui.user,
            ui.aws,
            table_name,
            limit=10,
        )
        st.session_state[sample_key] = {"rows": rows, "sampled": sampled}
    sample = st.session_state.get(sample_key)
    if isinstance(sample, dict):
        rows = sample.get("rows", [])
        sampled = sample.get("sampled", 0)
        st.caption(
            f"Atributos observados em {sampled} item(ns) da amostra. "
            "Isto não é schema da tabela e pode não representar todos os itens."
        )
        if isinstance(rows, list) and rows:
            render_summary_table(
                presentation_rows(rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Nenhum atributo foi observado na amostra carregada.")
    operation = st.selectbox(
        "Leitura do DynamoDB",
        ["get_item", "query"],
        format_func=display,
        index=1 if node.action == "dynamodb.query" else 0,
        key=f"{key}:operation",
    )
    if node.config and operation != node.action.split(".", 1)[1]:
        raise WorkflowValidationError(
            "Trocar Query por GetItem muda a saída de Items para Item e pode quebrar os vínculos. Crie outra etapa para essa operação; a atual foi preservada."
        )
    state = decode_read(operation, table, node.config)
    if type(state["limit"]) is not int or not 1 <= state["limit"] <= 100:
        raise WorkflowValidationError(
            "O limite atual está fora do intervalo deste construtor (1–100). Ele foi preservado; altere Limite na Configuração visual."
        )
    index_names = [""] + [
        entry["IndexName"]
        for entry in table.get("GlobalSecondaryIndexes", [])
        + table.get("LocalSecondaryIndexes", [])
        if isinstance(entry, dict) and isinstance(entry.get("IndexName"), str)
    ]
    index = st.selectbox(
        "Índice (opcional)",
        index_names,
        format_func=lambda value: value or "Chave primária da tabela",
        key=f"{key}:index",
        index=index_names.index(state["index"]) if state["index"] in index_names else 0,
    )
    fields = key_fields(table, index or "")
    values: dict[str, str] = {}
    parameters = {
        "{{ params." + name + " }}": name
        for name, spec in book.parameters.items()
        if spec.type == "string"
    }
    for field in fields:
        current = state["values"].get(field["name"], "")
        origins = [""] + list(parameters)
        origin = st.selectbox(
            f"Origem da chave {field['name']}",
            origins,
            index=origins.index(current) if current in origins else 0,
            format_func=lambda value: f"Parâmetro: {parameters[value]}" if value else "Valor fixo",
            key=f"{key}:{operation}:{index}:origin:{field['name']}",
        )
        values[field["name"]] = origin or st.text_input(
            f"Chave {field['name']} ({field['type']})",
            key=f"{key}:{operation}:{index}:key:{field['name']}",
            value=current,
        )
    sort_operator = ""
    sort_end = ""
    if operation == "query" and any(field["key_type"] == "RANGE" for field in fields):
        sort_operator = st.selectbox(
            "Condição da chave de ordenação",
            ["", "=", ">=", "<=", "begins_with", "between"],
            format_func=lambda value: display(value) if value else "Sem condição adicional",
            key=f"{key}:sort-op",
            index=["", "=", ">=", "<=", "begins_with", "between"].index(state["sort_operator"]),
        )
        if sort_operator == "between":
            sort_end = st.text_input(
                "Limite superior da chave de ordenação",
                value=state["sort_end"],
                key=f"{key}:sort-end",
            )
    limit = int(
        st.number_input(
            "Limite de leitura",
            min_value=1,
            max_value=100,
            value=state["limit"],
            step=1,
            key=f"{key}:limit",
        )
    )
    st.caption(
        "Query exige igualdade na chave de partição. Limite conta itens avaliados, não resultados após um filtro. A paginação do FlowOps (_flowops) é independente e será preservada. Chaves numéricas N são enviadas como texto decimal, sem conversão implícita de parâmetros."
    )
    if st.button(
        "Aplicar requisição DynamoDB gerada",
        key=f"{key}:apply-query",
        disabled=not ui._granted("runbook.edit", book),
    ):
        require(ui.user, "runbook.edit", book)
        generated = build_bound_read(
            operation,
            table,
            values,
            current=node.config,
            index=index or "",
            sort_operator=sort_operator,
            sort_end=sort_end,
            limit=limit,
        )
        node.action = f"dynamodb.{operation}"
        node.config = generated
        ui._store_working(book, revision)
        st.rerun()


def render_resource_picker(ui: Any, book: Any, node: Any, revision: int) -> None:
    """Render explicit, read-only discovery; mutations happen only on Apply buttons."""
    import streamlit as st

    metadata = ui.runtime.registry.get(node.action).metadata
    rules = discovery_rules(node.action, metadata.input_schema)
    support_rules = supporting_discovery_rules(node.action, metadata.input_schema)
    inspectors = {rule.field: rule for rule in inspection_rules(node.action, metadata.input_schema)}
    if not rules:
        return
    service = node.action.split(".", 1)[0]
    st.subheader("Buscar recursos AWS")
    st.caption(
        "A busca usa somente APIs de leitura, no contexto de conta e região desta sessão. "
        "Nada é aplicado automaticamente: escolha um valor descoberto e confirme sua aplicação."
    )
    key = f"flowops:resource-picker:{_fingerprint(ui, node.action, node.id)}"
    result_key = f"{key}:results"
    signature_key = f"{key}:result-signatures"
    auxiliary_key = f"{key}:auxiliary"
    auxiliary = st.session_state.get(auxiliary_key, {})
    if not isinstance(auxiliary, dict):
        auxiliary = {}
    discovery_context = dict(node.config)
    discovery_context.update(auxiliary)
    if st.button("Buscar recursos para esta etapa", key=f"{key}:discover"):
        results: dict[str, list[str]] = {}
        signatures: dict[str, str] = {}
        for rule in (*support_rules, *rules):
            if missing_dependencies(rule, discovery_context):
                continue
            try:
                results[rule.field] = discover_field(
                    ui.runtime.registry, ui.user, ui.aws, rule, discovery_context
                )
                signatures[rule.field] = _discovery_signature(ui, rule, discovery_context)
            except FlowOpsError as error:
                render_error(error)
        st.session_state[result_key] = results
        st.session_state[signature_key] = signatures

    results = st.session_state.get(result_key, {})
    if not isinstance(results, dict):
        results = {}
    signatures = st.session_state.get(signature_key, {})
    if not isinstance(signatures, dict):
        signatures = {}
    editable = ui._granted("runbook.edit", book)
    if support_rules:
        st.caption(
            "Alguns recursos exigem um contexto auxiliar apenas para a busca. "
            "Essas escolhas não são gravadas no procedimento."
        )
    for rule in support_rules:
        label = field_label(rule.field)
        missing = missing_dependencies(rule, discovery_context)
        if missing:
            st.caption(
                f"Contexto {label}: escolha primeiro "
                + ", ".join(field_label(field) for field in missing)
                + " e faça uma nova busca."
            )
            continue
        choices = results.get(rule.field, [])
        signature = _discovery_signature(ui, rule, discovery_context)
        if rule.request_from and signatures.get(rule.field) != signature:
            choices = []
            auxiliary.pop(rule.field, None)
            discovery_context.pop(rule.field, None)
            st.session_state[auxiliary_key] = auxiliary
        if not isinstance(choices, list) or not choices:
            st.caption(f"Contexto {label}: nenhuma opção carregada. Faça a busca para continuar.")
            continue
        current = auxiliary.get(rule.field)
        context_selected = st.selectbox(
            f"Contexto AWS para {label}",
            choices,
            index=choices.index(current) if current in choices else 0,
            key=f"{key}:aux-selected:{rule.field}",
        )
        auxiliary[rule.field] = context_selected
        discovery_context[rule.field] = context_selected
        st.session_state[auxiliary_key] = auxiliary

    selected_by_field: dict[str, Any] = {}
    for rule in rules:
        label = field_label(rule.field)
        missing = missing_dependencies(rule, discovery_context)
        if missing:
            st.caption(
                f"{label}: aplique primeiro "
                + ", ".join(field_label(field) for field in missing)
                + " como valor literal e faça uma nova busca."
            )
            continue
        choices = results.get(rule.field, [])
        current_signature = _discovery_signature(ui, rule, discovery_context)
        if rule.request_from and signatures.get(rule.field) != current_signature:
            choices = []
            st.caption(
                f"{label}: as dependências mudaram desde a última busca. "
                "Faça uma nova busca antes de selecionar este valor."
            )
        if not isinstance(choices, list) or not choices:
            st.caption(
                f"{label}: nenhuma opção carregada. Faça a busca ou informe o valor manualmente "
                "na Configuração visual."
            )
            continue

        current = node.config.get(rule.field)
        if rule.multiple:
            default = (
                [value for value in current if value in choices]
                if isinstance(current, list)
                else []
            )
            field_selected: Any = st.multiselect(
                f"Valores AWS para {label}",
                choices,
                default=default,
                key=f"{key}:selected:{rule.field}",
            )
        else:
            selector_label = "Recurso encontrado" if len(rules) == 1 else f"Valor AWS para {label}"
            field_selected = st.selectbox(
                selector_label,
                choices,
                index=choices.index(current) if current in choices else 0,
                key=f"{key}:selected:{rule.field}",
            )
        selected_by_field[rule.field] = field_selected
        inspector = inspectors.get(rule.field)
        if inspector is not None and field_selected:
            details_key = f"{key}:details:{rule.field}"
            if st.button(
                f"Carregar detalhes de {label}",
                key=f"{key}:inspect:{rule.field}",
            ):
                try:
                    details = inspect_resource(
                        ui.runtime.registry,
                        ui.user,
                        ui.aws,
                        inspector,
                        node.config,
                        field_selected,
                    )
                    st.session_state[details_key] = {
                        "selection": field_selected,
                        "signature": _inspection_signature(
                            ui, inspector, node.config, field_selected
                        ),
                        "result": details,
                    }
                except FlowOpsError as error:
                    render_error(error)
            details = st.session_state.get(details_key)
            details_signature = _inspection_signature(ui, inspector, node.config, field_selected)
            if (
                isinstance(details, dict)
                and details.get("selection") == field_selected
                and details.get("signature") == details_signature
            ):
                with st.expander(f"Detalhes AWS de {label}", expanded=False):
                    st.json(details.get("result"), expanded=False)

        apply_label = "Aplicar recurso selecionado" if len(rules) == 1 else f"Aplicar {label}"
        if st.button(
            apply_label,
            disabled=not editable,
            key=f"{key}:apply:{rule.field}",
        ):
            require(ui.user, "runbook.edit", book)
            _apply_resource(node, rule.field, field_selected)
            ui._store_working(book, revision)
            st.rerun()

    table_name = selected_by_field.get("TableName")
    if (
        service == "dynamodb"
        and node.action in {"dynamodb.get_item", "dynamodb.query"}
        and isinstance(table_name, str)
    ):
        try:
            _render_dynamodb_query(ui, book, node, revision, table_name, key=key)
        except FlowOpsError as error:
            render_error(error)
        except (KeyError, TypeError, ValueError, WorkflowValidationError) as error:
            render_error(error)
