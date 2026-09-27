"""Stage a parameter and its reference together, without altering the session draft."""

from typing import Any

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook
from flowops.streamlit.authoring import KINDS, EditBuffer, value_kind


def stage_parameter(
    buffer: EditBuffer,
    book: Runbook,
    path: tuple[str | int, ...],
    name: str,
    spec: dict[str, Any],
) -> None:
    from flowops.streamlit.parameter_editor import parse_parameters

    name = name.strip()
    if name in book.parameters or name in buffer.parameters:
        raise WorkflowValidationError("Esse parâmetro já existe. Selecione-o na origem do valor.")
    parameter = parse_parameters({name: spec})[name]
    # Validate the path before staging anything; both edits remain pending until Apply.
    buffer.at(path)
    buffer.put(path, "{{ params." + name + " }}")
    buffer.parameters[name] = parameter.model_dump(mode="json")
    buffer.structural_change()


def render_new_parameter(
    buffer: EditBuffer,
    book: Runbook,
    path: tuple[str | int, ...],
    label: str,
    key: str,
    editable: bool,
) -> None:
    import streamlit as st

    from flowops.domain.errors import FlowOpsError
    from flowops.streamlit.localization import render_error

    with st.expander(f"Criar parâmetro para {label}"):
        st.caption(
            "O parâmetro será solicitado ao executar. Nome, tipo e vínculo serão aplicados juntos ao confirmar a configuração da etapa."
        )
        name = st.text_input(
            f"Nome do parâmetro de {label}", key=key + ":name", disabled=not editable
        )
        kinds = [kind for kind in KINDS if kind not in {"reference", "null"}]
        current = buffer.at(path)
        current_kind = value_kind(current)
        kind = st.selectbox(
            f"Tipo do parâmetro de {label}",
            kinds,
            index=kinds.index(current_kind) if current_kind in kinds else 0,
            format_func=lambda value: KINDS[value],
            key=key + ":type",
            disabled=not editable,
        )
        required = st.checkbox(
            f"Exigir {label} na execução", value=True, key=key + ":required", disabled=not editable
        )
        description = st.text_input(
            f"Instrução de preenchimento de {label}",
            key=key + ":description",
            disabled=not editable,
        )
        use_default = st.checkbox(
            f"Usar valor atual de {label} como padrão",
            key=key + ":default",
            disabled=not editable or current_kind in {"reference", "null"},
        )
        if st.button(
            f"Preparar parâmetro e vínculo de {label}", key=key + ":prepare", disabled=not editable
        ):
            try:
                stage_parameter(
                    buffer,
                    book,
                    path,
                    name,
                    {
                        "type": kind,
                        "required": required,
                        "description": description,
                        "default": current
                        if use_default and current_kind not in {"reference", "null"}
                        else None,
                    },
                )
                st.rerun()
            except FlowOpsError as exc:
                render_error(exc)
