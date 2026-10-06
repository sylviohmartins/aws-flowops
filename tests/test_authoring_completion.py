import copy

import pytest
from streamlit.testing.v1 import AppTest

from flowops.domain.errors import WorkflowValidationError
from flowops.streamlit.authoring import EditBuffer
from flowops.streamlit.edit_history import EditHistory
from flowops.streamlit.field_parameters import stage_parameter
from flowops.streamlit.goal_wizard import DEFAULTS, build_goal, validate_step
from flowops.templates import dynamodb_query_lambda
from tests.test_visual_authoring import SCRIPT, widget


def test_staged_parameter_never_partially_alters_draft():
    book = dynamodb_query_lambda("author", "default")
    original = book.model_copy(deep=True)
    buffer = EditBuffer.create(book.nodes[1].config)
    for name, spec in (
        ("bad.name", {"type": "string"}),
        ("table_name", {"type": "string"}),
        ("new_name", {"type": "integer", "default": False}),
    ):
        with pytest.raises(WorkflowValidationError):
            stage_parameter(buffer, book, ("TableName",), name, spec)
        assert buffer.pristine() and book == original
    stage_parameter(buffer, book, ("Limit",), "read_limit", {"type": "integer", "default": 0})
    assert not buffer.pristine() and book == original
    assert buffer.parameters["read_limit"]["default"] == 0
    assert buffer.value["Limit"] == "{{ params.read_limit }}"


def test_inline_parameter_apply_is_atomic_and_discardable():
    app = AppTest.from_string(SCRIPT).run()
    widget(app, "text_input", ':["Name"]:parameter:name').set_value("source_name").run()
    widget(app, "button", ':["Name"]:parameter:prepare').click().run()
    assert not app.exception
    assert "source_name" not in app.session_state["flowops:working:visual-book"]["body"]
    widget(app, "button", ":apply").click().run()
    assert not app.exception and not app.error
    import json

    assert json.loads(app.json[-1].value)["Name"] == "{{ params.source_name }}"


def test_goal_creation_is_deterministic_safe_and_preserves_inputs():
    values = DEFAULTS | {
        "name": "Consultar pagamentos",
        "table": "payments",
        "payment": "12345",
        "function": "payment-processor",
        "filter": True,
    }
    original = copy.deepcopy(values)
    book = build_goal(values, "author", "ops")
    assert values == original and book.owner == "author"
    assert book.environments == ["dev"]
    nodes = {node.id: node for node in book.nodes}
    assert nodes["filter"].config["items"] == "{{ nodes.query.output.Items }}"
    assert nodes["prepare_event"].config["items"] == "{{ nodes.filter.output.items }}"
    assert nodes["invoke"].config["Payload"]["payments"] == "{{ nodes.prepare_event.output.items }}"
    for patch in (
        {"table": ""},
        {"partition": "{{ code }}"},
        {"id_field": "a.b"},
        {"limit": False},
        {"invocation": "bad"},
    ):
        with pytest.raises(WorkflowValidationError):
            build_goal(values | patch, "author", "ops")
    validate_step(values, 4)


def test_history_preserves_nested_types_and_invalidates_redo():
    history = EditHistory(4)
    history.record('{"v": false}', '{"v": 0}')
    history.record('{"v": 0}', '{"v": 0}')
    assert history.restore('{"v": 0}', 4) == '{"v": false}'
    assert history.restore('{"v": false}', 4, redo=True) == '{"v": 0}'
    assert history.restore('{"v": 0}', 4) == '{"v": false}'
    history.record('{"v": false}', '{"v": []}')
    assert not history.future
    with pytest.raises(WorkflowValidationError):
        history.restore("{}", 5)
    for i in range(50):
        history.record(str(i), str(i + 1))
    assert len(history.past) == 40
