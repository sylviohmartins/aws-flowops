import json

from streamlit.testing.v1 import AppTest

from tests.test_visual_authoring import widget

SCRIPT = """
from types import SimpleNamespace
import streamlit as st
from flowops.core.actions import Metadata
from flowops.domain.errors import FlowOpsError
from flowops.domain.models import AWSContext, Identity, Node, Runbook, Parameter
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.typed_inputs import render_typed_inputs
schema = {"type": "object", "required": ["Name"], "properties": {
    "Name": {"type": "string"}, "Count": {"type": "integer"},
    "Ratio": {"type": "number"}, "Active": {"type": "boolean"},
    "Mode": {"type": "string", "enum": ["slow", "fast"]},
    "Options": {"type": "object"}, "Items": {"type": "array"},
    "Message": {"type": "any"}, "Mapped": {"type": "integer"},
    "Optional": {"type": "string", "default": "default-value"},
}}
metadata = Metadata("test.typed", "test", "test", "typed", "Typed form fixture", input_schema=schema)
runtime = SimpleNamespace(repository=None, registry=SimpleNamespace(get=lambda action: SimpleNamespace(metadata=metadata)))
ui = FlowOpsUI(Identity(id="author", roles=["ADMIN"]), AWSContext(), runtime)
book = Runbook(id="typed-book", name="Typed inputs", parameters={"count": Parameter(type="integer")}, nodes=[Node(id="typed", action="test.typed", config={
    "Name": "old", "Count": 2, "Ratio": 0.5, "Active": True,
    "Mode": "slow", "Options": {"a": 1}, "Items": [1], "Message": "hello", "Mapped": "{{ params.count }}",
})])
working = ui._working_draft(book, 1)
try:
    render_typed_inputs(ui, working, working.nodes[0], 1)
except FlowOpsError as error:
    st.error(str(error))
st.json(working.nodes[0].config)
"""


def test_typed_inputs_preserve_types_mapping_and_reject_invalid_json() -> None:
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    widget(app, "selectbox", ":[]:add-field").set_value("Optional").run()
    widget(app, "button", ":[]:add").click().run()
    widget(app, "text_input", ':["Name"]:value').set_value("updated").run()
    widget(app, "number_input", ':["Count"]:value').set_value(4).run()
    widget(app, "number_input", ':["Ratio"]:value').set_value(1.5).run()
    widget(app, "checkbox", ':["Active"]:value').set_value(False).run()
    widget(app, "selectbox", ':["Mode"]:value').set_value("fast").run()
    app.radio[0].set_value("Editar JSON").run()
    edited = json.loads(app.text_area[0].value)
    edited.update(Options={"b": 2}, Items=[2, 3])
    app.text_area[0].set_value(json.dumps(edited)).run()
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    config = json.loads(app.json[-1].value)
    assert config == {
        "Name": "updated",
        "Count": 4,
        "Ratio": 1.5,
        "Active": False,
        "Mode": "fast",
        "Options": {"b": 2},
        "Items": [2, 3],
        "Message": "hello",
        "Mapped": "{{ params.count }}",
        "Optional": "default-value",
    }
    app.text_area[0].set_value("broken-json")
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    assert "JSON inválido" in app.error[0].value
    assert json.loads(app.json[-1].value) == config


def test_typed_inputs_are_readonly_for_viewers_and_accept_empty_schema() -> None:
    app = AppTest.from_string(SCRIPT.replace('roles=["ADMIN"]', 'roles=["VIEWER"]')).run()
    assert not app.exception
    assert all(field.disabled for field in app.text_input)
    assert app.button[0].disabled
    app = AppTest.from_string(
        SCRIPT.replace("input_schema=schema", 'input_schema={"type": "object"}')
    ).run()
    assert not app.exception
    assert widget(app, "text_input", ':["Name"]:value').value == "old"
    assert json.loads(app.json[-1].value)["Options"] == {"a": 1}
