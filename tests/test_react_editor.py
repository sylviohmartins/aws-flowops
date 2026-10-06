import copy

import pytest

from flowops.application import FlowOpsRuntime
from flowops.domain.errors import FlowOpsError, WorkflowValidationError
from flowops.domain.models import Identity
from flowops.persistence.repository import Repository, digest
from flowops.streamlit.react_editor import apply_command, editable_fields, editor_data
from flowops.templates import dynamodb_query_lambda


@pytest.fixture
def context(tmp_path):
    runtime = FlowOpsRuntime.demo(Repository(tmp_path / "react.db"))
    yield (
        runtime,
        dynamodb_query_lambda("author", "default"),
        Identity(id="author", roles=["ADMIN"]),
    )
    runtime.close()


def message(book, operations, **changes):
    return {
        "protocol": 1,
        "book_id": book.id,
        "revision": 1,
        "base": digest(book.model_dump()),
        "event_id": "test-1",
        "kind": "apply",
        "operations": operations,
    } | changes


def test_inline_patch_preserves_advanced_values_and_validates_types(context):
    runtime, book, user = context
    book.nodes[1].config["extra"] = {"huge": 2**60 + 1, "nil": None, "empty": [], "text": "kept"}
    before = copy.deepcopy(book)
    operations = [
        {"op": "value", "node": "query", "path": ["Limit"], "value": 4},
        {"op": "label", "node": "query", "value": "Ler pagamento"},
        {"op": "position", "node": "query", "value": [120, 42]},
    ]
    result = apply_command(book, 1, message(book, operations), user, runtime.registry)
    assert book == before and result.nodes[1].config["extra"] == before.nodes[1].config["extra"]
    assert result.nodes[1].config["Limit"] == 4 and result.nodes[1].position == (120, 42)
    assert result.nodes[1].label == "Ler pagamento"
    for patch in (["Limit"], ["extra", "huge"], ["missing"]):
        with pytest.raises(WorkflowValidationError):
            apply_command(
                book,
                1,
                message(book, [{"op": "value", "node": "query", "path": patch, "value": False}]),
                user,
                runtime.registry,
            )


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": 2},
        {"book_id": "other"},
        {"revision": 2},
        {"base": "stale"},
        {"kind": "draft"},
        {"owner": "forged"},
        {"operations": [{"op": "unknown", "node": "query"}]},
    ],
)
def test_bridge_rejects_stale_and_forged_messages_atomically(context, change):
    runtime, book, user = context
    before = book.model_copy(deep=True)
    with pytest.raises(WorkflowValidationError):
        apply_command(book, 1, message(book, []) | change, user, runtime.registry)
    assert book == before


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "value", "node": "missing", "path": ["Limit"], "value": 1},
        {"op": "value", "node": "query", "path": ["Limit"], "value": 2**54},
        {"op": "value", "node": "query", "path": ["Limit"], "value": 10**400},
        {"op": "value", "node": "query", "path": ["Limit"], "value": ""},
        {"op": "value", "node": "query", "path": ["Limit"], "value": {}},
        {"op": "label", "node": "query", "value": ""},
        {"op": "position", "node": "query", "value": [False, 0]},
        {"op": "position", "node": "query", "value": [1e6, 0]},
        {"op": "position", "node": "query", "value": [10**400, 0]},
        {"op": "config_json", "node": "query", "value": "{"},
        {"op": "config_json", "node": "query", "value": {}},
        {
            "op": "config_json",
            "node": "query",
            "value": '{"TableName":"{{ nodes.invoke.output }}"}',
        },
        {"op": "bind", "node": "invoke", "target": "FunctionName", "source": "params.missing"},
        {"op": "disconnect", "node": "query", "target": "start"},
        {"op": "connect", "node": "invoke", "target": "query"},
        {"op": "add", "node": "end", "value": "core.start"},
        {"op": "add", "node": "query", "value": "core.wait"},
        {"op": "remove", "node": "start"},
        {"op": "remove", "node": "query"},
    ],
)
def test_invalid_operations_cannot_partially_change_book(context, operation):
    runtime, book, user = context
    before = book.model_copy(deep=True)
    with pytest.raises(FlowOpsError):
        apply_command(
            book,
            1,
            message(book, [{"op": "label", "node": "invoke", "value": "Pending"}, operation]),
            user,
            runtime.registry,
        )
    assert book == before


def test_library_connections_bindings_and_auth(context):
    runtime, book, user = context
    ops = [{"op": "add", "node": "end", "value": "sqs.send_message"}]
    result = apply_command(book, 1, message(book, ops), user, runtime.registry)
    inserted = result.nodes[-1]
    assert inserted.action == "sqs.send_message" and inserted.config["MessageBody"] == {}
    result = apply_command(
        result, 1, message(result, [{"op": "remove", "node": inserted.id}]), user, runtime.registry
    )
    assert inserted.id not in {node.id for node in result.nodes}
    ops = [
        {"op": "connect", "node": "query", "target": "end"},
        {"op": "disconnect", "node": "query", "target": "end"},
        {
            "op": "bind",
            "node": "invoke",
            "target": "FunctionName",
            "source": "params.function_name",
        },
    ]
    result = apply_command(book, 1, message(book, ops), user, runtime.registry)
    assert result == book
    with pytest.raises(FlowOpsError):
        apply_command(
            book, 1, message(book, ops), Identity(id="viewer", roles=["VIEWER"]), runtime.registry
        )
    with pytest.raises(WorkflowValidationError):
        apply_command(
            book,
            1,
            message(book, [{"op": "label", "node": "query", "value": "x" * 250_000}]),
            user,
            runtime.registry,
        )
    data = editor_data(book, 1, runtime.registry)
    assert data["protocol"] == 1 and len(data["nodes"]) == 6 and data["actions"]
    assert all("config" not in node for node in data["nodes"])


def test_scalar_enumeration_bounds_and_preserves_opaque_subtrees():
    value = {
        "deep": {"deep": {"deep": {"deep": {"deep": {"deep": {"deep": {"deep": {"deep": 1}}}}}}}},
        "number": 10**400,
        "nested": [False, 0, "", None],
    }
    assert [field["value"] for field in editable_fields(value)] == [False, 0, ""]
    assert len(editable_fields({str(i): i for i in range(100)})) == 64


def test_json_editor_preserves_numbers_and_data_ports_do_not_replace_execution(context):
    import json

    runtime, book, user = context
    config = book.nodes[1].config | {"extra": {"huge": 10**400, "empty": [], "nil": None}}
    result = apply_command(
        book,
        1,
        message(book, [{"op": "config_json", "node": "query", "value": json.dumps(config)}]),
        user,
        runtime.registry,
    )
    assert result.nodes[1].config == config
    data = editor_data(result, 1, runtime.registry)
    assert all(edge["sourceHandle"] == "execution-out" for edge in data["edges"])
    assert all(edge["targetHandle"] == "execution-in" for edge in data["edges"])
    assert any(
        edge["sourceHandle"] == "data:nodes.query.output.Items" for edge in data["data_edges"]
    )
    query = next(node for node in data["nodes"] if node["id"] == "query")
    assert json.loads(query["data"]["config_json"]) == config
    assert query["data"]["sources"][0]["label"]
