"""Recursive visual configuration with explicit apply and persistent session buffers."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from flowops.core.expressions import path_parts, references
from flowops.core.mapping import (
    SchemaField,
    _ancestors,
    defaults_from_schema,
    validate_mapping_types,
)
from flowops.core.policies import require
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Node, Runbook
from flowops.streamlit.authoring import (
    KINDS,
    EditBuffer,
    authoring_sources,
    empty_value,
    reference_value,
    same_json,
    source_label,
    value_kind,
)
from flowops.streamlit.localization import display, field_help, field_label, render_error


def _validate_references(book: Runbook, node: Node, config: dict[str, Any], registry: Any) -> None:
    ancestors = _ancestors(book, node.id)
    for ref in references(config):
        parts = path_parts(ref)
        valid = (
            (parts[0] == "params" and len(parts) >= 2 and parts[1] in book.parameters)
            or (
                parts[0] == "nodes"
                and len(parts) >= 3
                and parts[1] in ancestors
                and parts[2] == "output"
            )
            or (
                parts[0] == "context"
                and ref
                in {
                    "context.account",
                    "context.region",
                    "context.environment",
                    "context.execution_id",
                }
            )
            or (parts[0] == "item" and node.action in {"core.map", "core.for_each"})
            or parts[0] == "input"
        )
        if not valid:
            raise WorkflowValidationError(
                "Origem indisponível: selecione um parâmetro existente ou a saída de uma etapa anterior; item só pode ser usado no mapeamento de uma lista."
            )
    for name, value in config.items():
        if name != "template" and any(path_parts(ref)[0] == "item" for ref in references(value)):
            raise WorkflowValidationError(
                "A origem Item só está disponível dentro do Modelo de Mapear itens; escolha uma lista de uma etapa anterior em Itens."
            )
    edited = node.model_copy(deep=True)
    edited.config = config
    validate_mapping_types(book, edited, ancestors, registry)


def _tree(
    buffer: EditBuffer,
    path: tuple[str | int, ...],
    schema: dict[str, Any],
    sources: list[SchemaField],
    key: str,
    editable: bool,
    *,
    depth: int = 0,
    book: Runbook | None = None,
) -> None:
    import streamlit as st

    value = buffer.at(path)
    if path and path[0] != "template":
        sources = [source for source in sources if source.path != "item"]
    label = field_label(str(path[-1])) if path else "Configuração"
    widget = f"{key}:{buffer.epoch}:{json.dumps(path, ensure_ascii=True)}"
    if depth > 8:
        st.info(
            f"{label}: estrutura profunda preservada. Use Editar JSON para alterar este trecho."
        )
        return

    def change_value(widget_key: str) -> None:
        if st.session_state.get(key) is not buffer or widget_key not in st.session_state:
            return
        buffer.put(path, st.session_state[widget_key])

    kind = buffer.kinds.get(path, value_kind(value))
    if path:

        def change_kind() -> None:
            # A dialog/fragment rerun can deliver a late callback after an
            # external builder has replaced this buffer. Never let a widget
            # from the old render mutate the current draft.
            if st.session_state.get(key) is not buffer:
                return
            selected = st.session_state[f"{widget}:kind"]
            if selected == kind:
                return
            buffer.put(path, empty_value(selected))
            buffer.structural_change()
            buffer.kinds[path] = selected

        st.selectbox(
            f"Tipo de {label}",
            list(KINDS),
            index=list(KINDS).index(kind),
            format_func=lambda kind: KINDS[kind],
            key=f"{widget}:kind",
            disabled=not editable,
            on_change=change_kind,
            help="Trocar o tipo substitui somente este valor no buffer. A etapa só muda ao aplicar.",
        )
        if book is not None:
            from flowops.streamlit.field_parameters import render_new_parameter

            render_new_parameter(buffer, book, path, label, widget + ":parameter", editable)
    if kind == "reference":
        current = str(value).strip().removeprefix("{{").removesuffix("}}").strip()
        matches = [s for s in sources if current == s.path or current.startswith(s.path + ".")]
        source = max(matches, key=lambda s: len(s.path)) if matches else None
        choices = [s.path for s in sources]
        selected = st.selectbox(
            f"Origem de {label}",
            choices,
            index=choices.index(source.path) if source else None,
            key=f"{widget}:source",
            disabled=not editable,
            placeholder="Selecione uma origem",
            format_func=lambda value: (
                source_label(book, next(s for s in sources if s.path == value))
                if book is not None
                else value
            ),
        )
        suffix = st.text_input(
            f"Campo dentro de {label} (opcional)",
            value=current[len(source.path) + 1 :] if source else "",
            key=f"{widget}:suffix",
            disabled=not editable,
            help="Para um objeto, informe o nome do campo, por exemplo status.S. Para listas, selecione a lista inteira e use Mapear itens.",
        )
        if selected:
            chosen = next(s for s in sources if s.path == selected)
            if chosen.type == "any" or suffix:
                st.caption(
                    "Tipo ainda desconhecido: a estrutura será conferida quando houver dados. Não há conversão automática."
                )
            if st.button(f"Usar origem em {label}", key=f"{widget}:bind", disabled=not editable):
                try:
                    buffer.put(
                        path, reference_value(chosen, suffix, str(schema.get("type", "any")))
                    )
                    buffer.structural_change()
                    st.rerun()
                except FlowOpsError as exc:
                    render_error(exc)
        elif current:
            st.warning(
                "Referência atual preservada, mas não disponível na lista de origens. Revise antes de aplicar."
            )
        return
    if kind in {"object", "array"}:
        properties = schema.get("properties", {})
        entries = list(value) if isinstance(value, dict) else list(range(len(value)))
        for child in entries:
            child_schema = (
                properties.get(child, schema.get("additionalProperties", {}))
                if kind == "object"
                else schema.get("items", {})
            )
            with st.container(border=True):
                st.markdown(
                    f"**{field_label(str(child)) if kind == 'object' else f'Item {int(child) + 1}'}**"
                )
                _tree(
                    buffer,
                    path + (child,),
                    child_schema if isinstance(child_schema, dict) else {},
                    sources,
                    key,
                    editable,
                    depth=depth + 1,
                    book=book,
                )
                if st.button(
                    f"Remover {child}", key=f"{widget}:remove:{child}", disabled=not editable
                ):
                    del value[child]
                    buffer.structural_change()
                    st.rerun()
                if (
                    kind == "array"
                    and int(child) > 0
                    and st.button(
                        f"Mover item {int(child) + 1} para cima",
                        key=f"{widget}:up:{child}",
                        disabled=not editable,
                    )
                ):
                    value[child - 1], value[child] = value[child], value[child - 1]
                    buffer.structural_change()
                    st.rerun()
        if kind == "object":
            options = [name for name in properties if name not in value]
            selected_field = st.selectbox(
                f"Campo disponível em {label}",
                [""] + options,
                format_func=lambda name: field_label(name) if name else "Outro campo",
                key=f"{widget}:add-field",
                disabled=not editable,
            )
            name = selected_field or st.text_input(
                f"Nome do novo campo em {label}", key=f"{widget}:new-name", disabled=not editable
            )
            if st.button(
                f"Adicionar campo em {label}",
                key=f"{widget}:add",
                disabled=not editable,
            ):
                if not name or name in value:
                    st.error("Informe um nome de campo ainda não utilizado neste objeto.")
                    return
                field_schema = properties.get(name, schema.get("additionalProperties", {}))
                if not isinstance(field_schema, dict):
                    field_schema = {}
                value[name] = copy.deepcopy(
                    field_schema.get(
                        "default",
                        empty_value(
                            field_schema.get("type", "string")
                            if field_schema.get("type") in KINDS
                            else "string"
                        ),
                    )
                )
                if isinstance(value[name], dict):
                    value[name].update(defaults_from_schema(field_schema))
                buffer.structural_change()
                st.rerun()
        elif st.button(f"Adicionar item em {label}", key=f"{widget}:add", disabled=not editable):
            item_kind = schema.get("items", {}).get("type", "string")
            value.append(empty_value(item_kind if item_kind in KINDS else "string"))
            buffer.structural_change()
            st.rerun()
        return
    args: dict[str, Any] = {
        "key": f"{widget}:value",
        "disabled": not editable,
        "on_change": change_value,
        "args": (f"{widget}:value",),
        "help": field_help(str(path[-1]), schema),
    }
    if kind == "null":
        st.caption("Valor nulo explícito. Remover o campo é diferente de informar nulo.")
    elif kind == "boolean":
        st.checkbox(label, value=value, **args)
    elif kind in {"integer", "number"} and abs(value) <= 2**53 - 1:
        st.number_input(label, value=value, step=1 if kind == "integer" else 0.1, **args)
    elif kind in {"integer", "number"}:
        st.info("Número fora da precisão do controle visual, preservado. Edite pelo modo JSON.")
    elif schema.get("enum") and value in schema["enum"]:
        st.selectbox(
            label, schema["enum"], index=schema["enum"].index(value), format_func=display, **args
        )
    else:
        st.text_input(label, value=value, **args)


def render_config_editor(
    ui: Any,
    book: Runbook,
    node: Node,
    revision: int,
    schema: dict[str, Any],
    *,
    title: str = "Configuração visual",
    apply_config: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    import streamlit as st

    st.subheader(title)
    st.caption(
        "Preencha os campos ou escolha a origem dos valores. Alterações ficam nesta sessão até aplicar; aplicar não executa nem publica o fluxo."
    )
    editable = ui._granted("runbook.edit", book)
    key = f"flowops:visual:{book.id}:{node.id}:{node.action}"
    if key not in st.session_state:
        st.session_state[key] = EditBuffer.create(node.config)
    buffer: EditBuffer = st.session_state[key]
    if not same_json(buffer.base, node.config) and buffer.pristine():
        refreshed = EditBuffer.create(node.config)
        refreshed.epoch = buffer.epoch + 1
        refreshed.mode = buffer.mode
        st.session_state[key] = buffer = refreshed
    mode_key = key + ":mode"

    def switch_mode() -> None:
        if st.session_state.get(key) is not buffer or mode_key not in st.session_state:
            return
        try:
            buffer.switch(st.session_state[mode_key])
            st.session_state.pop(key + ":error", None)
        except FlowOpsError as exc:
            st.session_state[key + ":error"] = str(exc)
            st.session_state[mode_key] = buffer.mode

    st.radio(
        "Modo dos parâmetros" if apply_config else "Modo de configuração",
        ["Visual", "Ver JSON", "Editar JSON"],
        horizontal=True,
        index=["Visual", "Ver JSON", "Editar JSON"].index(buffer.mode),
        key=mode_key,
        on_change=switch_mode,
    )
    if st.session_state.get(key + ":error"):
        st.error(st.session_state[key + ":error"])
    if not same_json(buffer.base, node.config):
        st.warning(
            "A etapa mudou fora deste editor. O buffer foi preservado; carregue a configuração atual antes de aplicar."
        )
        st.json(buffer.value, expanded=False)
        if st.button(
            "Carregar configuração atual (descarta este buffer)",
            key=key + ":reload",
            disabled=not editable,
        ):
            replacement = EditBuffer.create(node.config)
            replacement.epoch = buffer.epoch + 1
            st.session_state[key] = replacement
            st.session_state.pop(mode_key, None)
            st.rerun()
    if buffer.mode == "Visual":
        source_book = book.model_copy(deep=True)
        if buffer.parameters:
            from flowops.streamlit.parameter_editor import parse_parameters

            source_book.parameters.update(parse_parameters(buffer.parameters))
        sources = (
            authoring_sources(source_book, node.id, ui.runtime.registry)
            if apply_config is None
            else []
        )
        if node.action in {"core.map", "core.for_each"}:
            sources.append(SchemaField("item", "any"))
        _tree(
            buffer, (), schema, sources, key, editable, book=book if apply_config is None else None
        )
    elif buffer.mode == "Editar JSON":
        raw_key = f"{key}:{buffer.epoch}:raw"

        def capture_raw() -> None:
            if st.session_state.get(key) is not buffer or raw_key not in st.session_state:
                return
            buffer.raw = st.session_state[raw_key]

        st.text_area(
            "Código JSON dos parâmetros" if apply_config else "Código JSON da configuração",
            value=buffer.raw,
            key=raw_key,
            height=320,
            disabled=not editable,
            on_change=capture_raw,
        )
        st.caption(
            "Se o JSON estiver inválido, o texto não será perdido. A prévia abaixo é a última versão visual válida."
        )
        st.json(buffer.value, expanded=False)
    else:
        st.json(buffer.value, expanded=False)
    if node.action in {"core.map", "core.filter", "core.for_each", "core.batch"}:
        st.caption(
            "Prévia opcional com um pagamento fictício: paymentId, status e amount. Não consulta AWS, não usa valores reais de parâmetros e não garante o resultado de uma execução."
        )
        if st.button("Prévia fictícia da transformação", key=key + ":sample"):
            from flowops.streamlit.collection_preview import collection_preview

            try:
                st.json(collection_preview(book, node, buffer.candidate(node.config)))
            except FlowOpsError as exc:
                render_error(exc)
    if st.button(
        "Aplicar parâmetros ao rascunho" if apply_config else "Aplicar configuração ao rascunho",
        type="primary",
        key=key + ":apply",
        disabled=not editable,
    ):
        try:
            require(ui.user, "runbook.edit", book)
            candidate = buffer.candidate(node.config)
            if apply_config is None:
                from flowops.streamlit.parameter_editor import parse_parameters

                proposed = book.model_copy(deep=True)
                if buffer.parameters:
                    if set(buffer.parameters) & book.parameters.keys():
                        raise WorkflowValidationError(
                            "Um parâmetro preparado já foi criado em outro editor. Descarte o buffer e escolha a origem existente."
                        )
                    parameter_buffer = st.session_state.get(
                        f"flowops:visual:{book.id}:parameters:core.parameters"
                    )
                    if isinstance(parameter_buffer, EditBuffer) and not parameter_buffer.pristine():
                        raise WorkflowValidationError(
                            "Aplique ou descarte primeiro as alterações pendentes no editor de parâmetros."
                        )
                    proposed.parameters.update(parse_parameters(buffer.parameters))
                _validate_references(proposed, node, candidate, ui.runtime.registry)
                book.parameters = proposed.parameters
            else:
                apply_config(candidate)
            node.config = candidate
            ui._store_working(book, revision)
            updated = EditBuffer.create(candidate)
            updated.epoch = buffer.epoch + 1
            updated.mode = buffer.mode
            st.session_state[key] = updated
            st.rerun()
        except FlowOpsError as exc:
            render_error(exc)
    if not buffer.pristine() and st.button(
        "Descartar alterações não aplicadas", key=key + ":discard", disabled=not editable
    ):
        replacement = EditBuffer.create(node.config)
        replacement.epoch = buffer.epoch + 1
        st.session_state[key] = replacement
        st.session_state.pop(mode_key, None)
        st.rerun()
