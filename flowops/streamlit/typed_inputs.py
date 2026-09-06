"""Schema-driven controls for literals; mappings remain expressions in the same config."""

import json
import re
from typing import Any

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Node, Runbook
from flowops.persistence.repository import digest
from flowops.streamlit.ui import FlowOpsUI


def render_typed_inputs(ui: FlowOpsUI, book: Runbook, node: Node, revision: int) -> None:
    import streamlit as st

    schema = ui.runtime.registry.get(node.action).metadata.input_schema
    properties = schema.get("properties", {})
    if not properties:
        return
    required = schema.get("required", [])
    editable = ui._granted("runbook.edit", book)
    with st.expander("Typed inputs", expanded=False):
        fields = st.multiselect(
            "Input fields",
            list(properties),
            default=[name for name in properties if name in node.config or name in required],
            key=f"flowops:typed-fields:{book.id}:{node.id}",
            disabled=not editable,
        )
        values: dict[str, Any] = {}
        with st.form(f"flowops:typed:{book.id}:{node.id}:{digest(node.config)}"):
            for name in fields:
                field = properties[name]
                value = node.config.get(name, field.get("default"))
                label = f"{name}{' *' if name in required else ''}"
                help_text = re.sub(r"<[^>]+>", "", field.get("description", ""))
                kind = field.get("type", "any")
                if isinstance(value, str) and "{{" in value:
                    values[name] = st.text_input(
                        label, value=value, help=help_text, disabled=not editable
                    )
                elif field.get("enum"):
                    options = list(field["enum"])
                    values[name] = st.selectbox(
                        label,
                        options,
                        index=options.index(value) if value in options else 0,
                        help=help_text,
                        disabled=not editable,
                    )
                elif kind in {"integer", "number"}:
                    values[name] = st.number_input(
                        label,
                        value=value,
                        step=1 if kind == "integer" else 0.1,
                        help=help_text,
                        disabled=not editable,
                    )
                elif kind == "boolean":
                    values[name] = st.checkbox(
                        label, value=bool(value), help=help_text, disabled=not editable
                    )
                elif kind == "string":
                    values[name] = st.text_input(
                        label, value=value or "", help=help_text, disabled=not editable
                    )
                else:
                    raw = st.text_area(
                        label + " (JSON)",
                        value=json.dumps(
                            value
                            if value is not None
                            else {}
                            if kind == "object"
                            else []
                            if kind == "array"
                            else ""
                        ),
                        help=help_text,
                        disabled=not editable,
                    )
                    values[name] = ("json", raw)
            applied = st.form_submit_button("Apply typed inputs", disabled=not editable)
        if applied:
            parsed: dict[str, Any] = {}
            for name, value in values.items():
                try:
                    parsed[name] = json.loads(value[1]) if isinstance(value, tuple) else value
                except ValueError as exc:
                    raise WorkflowValidationError(f"{name} must contain valid JSON.") from exc
            node.config.update(parsed)
            ui._store_working(book, revision)
            st.rerun()
