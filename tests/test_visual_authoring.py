import copy
import json

import pytest
from streamlit.testing.v1 import AppTest

from flowops.core.mapping import SchemaField
from flowops.domain.errors import WorkflowValidationError
from flowops.streamlit.authoring import EditBuffer, empty_value, reference_value, value_kind


def test_edit_buffer_roundtrip_keeps_absence_null_false_zero_nested_and_advanced() -> None:
    config = {
        "false": False,
        "zero": 0,
        "empty": "",
        "null": None,
        "list": [],
        "object": {},
        "nested": [{"event": {"amount": "1.2300"}}],
        "_flowops": {"paginate": True},
        "ProjectionExpression": "#name",
    }
    original = copy.deepcopy(config)
    buffer = EditBuffer.create(config)
    buffer.put(("nested", 0, "event", "amount"), "5.60")
    assert config == original
    buffer.switch("Editar JSON")
    assert buffer.candidate(config)["nested"][0]["event"]["amount"] == "5.60"
    buffer.switch("Visual")
    assert buffer.value.keys() == config.keys()
    assert buffer.value["_flowops"] == config["_flowops"]
    assert buffer.value["false"] is False and buffer.value["null"] is None
    buffer.raw = "broken"
    buffer.mode = "Editar JSON"
    with pytest.raises(WorkflowValidationError, match="mantido"):
        buffer.switch("Visual")
    assert buffer.raw == "broken" and buffer.mode == "Editar JSON"
    for raw in ("[]", "null", '{"n": NaN}', '{"n": Infinity}'):
        buffer.raw = raw
        with pytest.raises(WorkflowValidationError):
            buffer.candidate(config)
    with pytest.raises(WorkflowValidationError, match="mudou"):
        buffer.candidate({"external": 1})


def test_explicit_kinds_and_typed_origins_never_coerce_or_pick_first_item() -> None:
    for kind in ("string", "integer", "number", "boolean", "object", "array", "null"):
        assert value_kind(empty_value(kind)) == kind
    assert value_kind("{{ params.name }}") == "reference"
    assert reference_value(SchemaField("params.x", "integer"), "", "number") == "{{ params.x }}"
    assert (
        reference_value(SchemaField("item", "any"), "status.S", "string") == "{{ item.status.S }}"
    )
    with pytest.raises(WorkflowValidationError, match="incompatíveis"):
        reference_value(SchemaField("params.x", "string"), "", "integer")
    with pytest.raises(WorkflowValidationError, match="lista inteira"):
        reference_value(SchemaField("nodes.query.output.Items", "array"), "status", "any")
    with pytest.raises(WorkflowValidationError):
        reference_value(SchemaField("item", "any"), "bad-key", "any")


@pytest.mark.parametrize("before,after", [(0, False), (1, True), (0, 0.0)])
def test_buffer_detects_json_type_changes_even_when_python_values_compare_equal(before, after):
    original = {"nested": [{"value": before}]}
    changed = {"nested": [{"value": after}]}
    buffer = EditBuffer.create(original)
    buffer.put(("nested", 0, "value"), after)
    assert not buffer.pristine()
    buffer.switch("Editar JSON")
    assert not buffer.pristine()
    with pytest.raises(WorkflowValidationError, match="mudou"):
        buffer.candidate(changed)


SCRIPT = """
from types import SimpleNamespace
import streamlit as st
from flowops.core.actions import Metadata
from flowops.domain.models import AWSContext, Identity, Node, Runbook, Parameter
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.typed_inputs import render_typed_inputs
metadata = Metadata("test.typed", "test", "test", "typed", "fixture", input_schema={
    "type": "object", "properties": {"Name": {"type": "string"},
    "Count": {"type": "integer"}, "Options": {"type": "object"}}})
runtime = SimpleNamespace(repository=None, registry=SimpleNamespace(get=lambda _: SimpleNamespace(metadata=metadata)))
ui = FlowOpsUI(Identity(id="author", roles=["ADMIN"]), AWSContext(), runtime)
book = Runbook(id="visual-book", name="Visual", parameters={"count": Parameter(type="integer")},
    nodes=[Node(id="typed", action="test.typed", config={"Name": "old", "Count": 2,
      "Options": {"a": [{"active": False, "empty": None}]}, "_flowops": {"max_pages": 2}})])
working = ui._working_draft(book, 1)
if st.checkbox("Mostrar editor", value=True):
    render_typed_inputs(ui, working, working.nodes[0], 1)
st.json(working.nodes[0].config)
"""


def widget(app, kind, suffix):
    return next(w for w in getattr(app, kind) if w.key and w.key.endswith(suffix))


def test_visual_session_buffer_survives_navigation_and_applies_only_explicitly() -> None:
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    widget(app, "text_input", ':["Name"]:value').set_value("updated").run()
    widget(app, "number_input", ':["Count"]:value').set_value(0).run()
    assert json.loads(app.json[-1].value)["Name"] == "old"
    app.checkbox[0].set_value(False).run()
    app.checkbox[0].set_value(True).run()
    assert widget(app, "text_input", ':["Name"]:value').value == "updated"
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    result = json.loads(app.json[-1].value)
    assert result["Name"] == "updated" and result["Count"] == 0
    assert result["Options"] == {"a": [{"active": False, "empty": None}]}
    assert result["_flowops"] == {"max_pages": 2}


def test_invalid_code_buffer_survives_navigation_and_blocks_mode_switch() -> None:
    app = AppTest.from_string(SCRIPT).run()
    app.radio[0].set_value("Editar JSON").run()
    app.text_area[0].set_value("incompleto {").run()
    widget(app, "button", ":apply").click().run()
    assert app.error and not app.exception
    app.radio[0].set_value("Visual").run()
    assert app.radio[0].value == "Editar JSON"
    app.checkbox[0].set_value(False).run()
    app.checkbox[0].set_value(True).run()
    assert app.text_area[0].value == "incompleto {"
    assert json.loads(app.json[-1].value)["Name"] == "old"
    widget(app, "button", ":discard").click().run()
    assert app.radio[0].value == "Visual" and not app.exception
    assert widget(app, "text_input", ':["Name"]:value').value == "old"


def test_visual_reference_selection_and_viewer_controls() -> None:
    app = AppTest.from_string(SCRIPT).run()
    widget(app, "selectbox", ':["Count"]:kind').set_value("reference").run()
    widget(app, "selectbox", ':["Count"]:source').set_value("params.count").run()
    widget(app, "button", ':["Count"]:bind').click().run()
    widget(app, "button", ":apply").click().run()
    assert not app.exception
    assert json.loads(app.json[-1].value)["Count"] == "{{ params.count }}"
    viewer = AppTest.from_string(SCRIPT.replace('roles=["ADMIN"]', 'roles=["VIEWER"]')).run()
    assert not viewer.exception
    assert all(w.disabled for w in viewer.text_input)
    assert all(w.disabled for w in viewer.button)
