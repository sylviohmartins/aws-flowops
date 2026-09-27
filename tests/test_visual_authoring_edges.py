import json

import pytest
from streamlit.testing.v1 import AppTest

from flowops.domain.errors import WorkflowValidationError
from flowops.streamlit.parameter_editor import parse_parameters
from tests.test_visual_authoring import SCRIPT, widget


def test_late_type_callback_cannot_erase_a_reloaded_reference(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from flowops.core.mapping import SchemaField
    from flowops.streamlit.authoring import EditBuffer
    from flowops.streamlit.value_editor import _tree

    callbacks = []
    state = {}

    def selectbox(label, choices, *, index=0, key, **kwargs):
        selected = choices[index] if index is not None else None
        state[key] = selected
        if "on_change" in kwargs:
            callbacks.append(kwargs["on_change"])
        return selected

    fake = SimpleNamespace(
        session_state=state,
        selectbox=selectbox,
        text_input=lambda label, **kwargs: kwargs.get("value", ""),
        button=lambda *args, **kwargs: False,
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    buffer = EditBuffer.create({"TableName": "{{ params.table_name }}"})
    state["fixture"] = buffer
    _tree(
        buffer,
        ("TableName",),
        {"type": "string"},
        [SchemaField("params.table_name", "string")],
        "fixture",
        True,
    )
    replacement = EditBuffer.create(buffer.value)
    state["fixture"] = replacement
    state['fixture:0:["TableName"]:kind'] = "string"
    callbacks[0]()
    assert replacement.pristine()
    assert replacement.value["TableName"] == "{{ params.table_name }}"


def test_pending_buffers_block_publication_but_ignore_removed_nodes() -> None:
    from flowops.streamlit.authoring import EditBuffer, pending_buffers, require_applied_buffers
    from flowops.templates import dynamodb_query_lambda

    book = dynamodb_query_lambda("author", "default")
    buffer = EditBuffer.create({"Limit": 30})
    session = {f"flowops:visual:{book.id}:query:dynamodb.query": buffer}
    assert pending_buffers(book, session) == []
    require_applied_buffers(book, session)
    buffer.put(("Limit",), 5)
    with pytest.raises(WorkflowValidationError, match="não aplicados"):
        require_applied_buffers(book, session)
    buffer.mode = "Editar JSON"
    buffer.raw = "invalid"
    assert not buffer.pristine()
    assert pending_buffers(book, session) == ["query"]
    session[f"flowops:visual:{book.id}:parameters:core.parameters"] = buffer
    book.nodes = [node for node in book.nodes if node.id != "query"]
    assert pending_buffers(book, session) == ["parâmetros"]


def test_parameter_types_defaults_and_names_preserve_contract() -> None:
    for kind, default in (
        ("boolean", False),
        ("integer", 0),
        ("number", 0.0),
        ("array", []),
        ("object", {}),
        ("string", ""),
        ("string", "{{ literal }}"),
    ):
        parsed = parse_parameters({"value": {"type": kind, "default": default}})
        assert parsed["value"].default == default
    assert parse_parameters({"value": {"type": "string", "default": None}})["value"].default is None
    for config in (
        {"bad.name": {}},
        {"bad-name": {}},
        {"ok": {"type": "invalid"}},
        {"ok": {"type": "integer", "default": False}},
    ):
        with pytest.raises(WorkflowValidationError):
            parse_parameters(config)


def test_parameters_can_be_created_and_reedited_without_code() -> None:
    script = """
from types import SimpleNamespace
import streamlit as st
from flowops.domain.models import AWSContext, Identity, Runbook
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.parameter_editor import render_parameter_editor
ui = FlowOpsUI(Identity(id="author", roles=["ADMIN"]), AWSContext(), SimpleNamespace(repository=None))
book = Runbook(id="parameters-ui", name="Parameters")
working = ui._working_draft(book, 1)
render_parameter_editor(ui, working, 1)
st.json({name: spec.model_dump() for name, spec in working.parameters.items()})
"""
    app = AppTest.from_string(script).run()
    widget(app, "text_input", ":[]:new-name").set_value("limit").run()
    widget(app, "button", ":[]:add").click().run()
    widget(app, "selectbox", ':["limit", "type"]:value').set_value("integer").run()
    widget(app, "selectbox", ':["limit"]:add-field').set_value("default").run()
    widget(app, "button", ':["limit"]:add').click().run()
    widget(app, "selectbox", ':["limit", "default"]:kind').set_value("integer").run()
    widget(app, "number_input", ':["limit", "default"]:value').set_value(0).run()
    widget(app, "selectbox", ':["limit"]:add-field').set_value("description").run()
    widget(app, "button", ':["limit"]:add').click().run()
    widget(app, "text_input", ':["limit", "description"]:value').set_value(
        "Quantidade máxima"
    ).run()
    assert json.loads(app.json[-1].value) == {}
    widget(app, "button", ":apply").click().run()
    assert not app.exception and not app.error
    assert json.loads(app.json[-1].value)["limit"] == {
        "type": "integer",
        "required": True,
        "default": 0,
        "description": "Quantidade máxima",
    }
    widget(app, "checkbox", ':["limit", "required"]:value').set_value(False).run()
    widget(app, "button", ":apply").click().run()
    assert json.loads(app.json[-1].value)["limit"]["required"] is False
    assert not app.text_area


def test_visual_list_add_reorder_remove_without_json() -> None:
    app = AppTest.from_string(SCRIPT).run()
    widget(app, "button", ':["Options", "a"]:add').click().run()
    widget(app, "text_input", ':["Options", "a", 1]:value').set_value("second").run()
    widget(app, "button", ':["Options", "a"]:up:1').click().run()
    assert widget(app, "text_input", ':["Options", "a", 0]:value').value == "second"
    widget(app, "button", ':["Options", "a"]:remove:1').click().run()
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    assert json.loads(app.json[-1].value)["Options"] == {"a": ["second"]}


def test_unknown_fields_edit_visually_and_conflict_requires_explicit_reload() -> None:
    script = SCRIPT.replace(
        'if st.checkbox("Mostrar editor", value=True):',
        """if st.button("Alteração externa"):
    working.nodes[0].config["external"] = 1
    ui._store_working(working, 1)
if st.checkbox("Mostrar editor", value=True):""",
    )
    app = AppTest.from_string(script).run()
    widget(app, "text_input", ':["Name"]:value').set_value("pending").run()
    app.button[0].click().run()
    widget(app, "button", ":apply").click().run()
    assert app.error and not app.exception
    assert widget(app, "text_input", ':["Name"]:value').value == "pending"
    widget(app, "button", ":reload").click().run()
    assert not app.exception
    assert widget(app, "text_input", ':["Name"]:value').value == "old"
    widget(app, "text_input", ":[]:new-name").set_value("extra").run()
    widget(app, "button", ":[]:add").click().run()
    widget(app, "text_input", ':["extra"]:value').set_value("kept").run()
    app.radio[0].set_value("Ver JSON").run()
    widget(app, "button", ":apply").click().run()
    assert json.loads(app.json[-1].value)["extra"] == "kept"


def test_broken_reference_and_item_scope_cannot_be_applied() -> None:
    for expression in ("{{ params.missing }}", "{{ nodes.next.output }}", "{{ item.name }}"):
        app = AppTest.from_string(SCRIPT).run()
        app.radio[0].set_value("Editar JSON").run()
        app.text_area[0].set_value(json.dumps({"Name": expression})).run()
        widget(app, "button", ":apply").click().run()
        assert app.error and not app.exception
        assert json.loads(app.json[-1].value)["Name"] == "old"
    app = AppTest.from_string(SCRIPT.replace('action="test.typed"', 'action="core.map"')).run()
    app.radio[0].set_value("Editar JSON").run()
    app.text_area[0].set_value('{"items": "{{ item.items }}", "template": {}}').run()
    widget(app, "button", ":apply").click().run()
    assert app.error and not app.exception


def test_schema_known_incompatible_source_and_unsupported_visual_values_preserved() -> None:
    app = AppTest.from_string(SCRIPT).run()
    widget(app, "selectbox", ':["Count"]:kind').set_value("reference").run()
    widget(app, "selectbox", ':["Count"]:source').set_value("context.region").run()
    widget(app, "button", ':["Count"]:bind').click().run()
    assert app.error and not app.exception
    # Arbitrary precision integers and deep structures cannot pass through lossy controls.
    huge = 2**60 + 1
    nested = {"value": True}
    for _ in range(9):
        nested = {"level": nested}
    original = {"Count": huge, "Options": nested}
    app.radio[0].set_value("Editar JSON").run()
    app.text_area[0].set_value(json.dumps(original)).run()
    app.radio[0].set_value("Visual").run()
    assert any("precisão" in item.value for item in app.info)
    assert any("profunda preservada" in item.value for item in app.info)
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    assert json.loads(app.json[-1].value) == original
