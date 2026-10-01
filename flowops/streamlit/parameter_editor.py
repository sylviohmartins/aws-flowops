"""Visual definitions for runbook parameters, using the existing Parameter contract."""

from typing import Any

from pydantic import ValidationError

from flowops.core.expressions import path_parts
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Node, Parameter, Runbook
from flowops.streamlit.authoring import value_kind
from flowops.streamlit.value_editor import render_config_editor


def parse_parameters(config: dict[str, Any]) -> dict[str, Parameter]:
    parsed: dict[str, Parameter] = {}
    for name, value in config.items():
        if len(path_parts("params." + name)) != 2:
            raise WorkflowValidationError(
                "O nome do parâmetro deve conter apenas letras, números e sublinhado, começando com uma letra."
            )
        try:
            spec = Parameter.model_validate(value)
        except ValidationError as exc:
            raise WorkflowValidationError(
                "Revise os campos do parâmetro: tipo, obrigatório, padrão e descrição."
            ) from exc
        kind = value_kind(spec.default)
        if kind == "reference":
            kind = "string"  # Parameter defaults are literal strings, not evaluated expressions.
        if (
            spec.default is not None
            and kind != spec.type
            and not (kind == "integer" and spec.type == "number")
        ):
            raise WorkflowValidationError(
                "O valor padrão deve ter o mesmo tipo do parâmetro; não há conversão automática."
            )
        parsed[name] = spec
    return parsed


def render_parameter_editor(ui: Any, book: Runbook, revision: int) -> None:
    import streamlit as st

    st.caption(
        "Parâmetros são valores solicitados ao iniciar o fluxo. Dê um nome estável, escolha o tipo e explique o preenchimento na descrição. Um padrão nulo equivale a não ter padrão no contrato atual."
    )
    node = Node(
        id="parameters",
        action="core.parameters",
        config={name: spec.model_dump(mode="json") for name, spec in book.parameters.items()},
    )
    schema = {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["string", "integer", "number", "boolean", "array", "object"],
                    "default": "string",
                },
                "required": {"type": "boolean", "default": True},
                "default": {"type": "any"},
                "description": {"type": "string"},
            },
        },
    }

    def apply(config: dict[str, Any]) -> None:
        book.parameters = parse_parameters(config)

    render_config_editor(
        ui, book, node, revision, schema, title="Parâmetros do procedimento", apply_config=apply
    )
