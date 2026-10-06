"""Schema-driven visual inputs, retaining the canonical node configuration."""

from flowops.domain.models import Node, Runbook
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.value_editor import render_config_editor


def render_typed_inputs(ui: FlowOpsUI, book: Runbook, node: Node, revision: int) -> None:
    from flowops.streamlit.action_forms import render_action_help

    render_action_help(node.action)
    schema = ui.runtime.registry.get(node.action).metadata.input_schema
    render_config_editor(ui, book, node, revision, schema)
