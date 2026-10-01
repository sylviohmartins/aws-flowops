import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Node
from flowops.streamlit.collection_preview import collection_preview
from flowops.templates import dynamodb_query_lambda


def test_fictitious_collection_preview_is_pure_and_uses_no_parameter_defaults() -> None:
    book = dynamodb_query_lambda("author", "default")
    book.parameters["payment_id"].default = "private-value-not-for-preview"
    original = book.model_copy(deep=True)
    node = next(node for node in book.nodes if node.id == "prepare_event")
    sample = collection_preview(book, node, node.config)
    assert sample == {"items": [{"payment_id": "12345", "status": "PROCESSING"}]}
    assert book == original
    sample = collection_preview(book, node, node.config | {"template": "{{ params.payment_id }}"})
    assert sample == {"items": ["exemplo"]}
    node.action = "core.filter"
    filtered = collection_preview(
        book,
        node,
        {
            "items": "{{ nodes.query.output.Items }}",
            "path": "status.S",
            "operator": "eq",
            "value": "DONE",
        },
    )
    assert filtered == {"items": []}
    with pytest.raises(WorkflowValidationError, match="exemplo fictício"):
        collection_preview(book, node, {"items": [{"status": {"S": "DONE"}}]})
    with pytest.raises(WorkflowValidationError):
        collection_preview(book, node, {"items": "{{ nodes.query.output.missing }}"})
    node.action = "lambda.invoke"
    with pytest.raises(WorkflowValidationError, match="somente"):
        collection_preview(book, node, {})
    query = next(node for node in book.nodes if node.id == "query")
    query.action = "dynamodb.get_item"
    node.action = "core.map"
    result = collection_preview(
        book, node, {"items": ["{{ nodes.query.output.Item }}"], "template": "{{ item.amount.N }}"}
    )
    assert result == {"items": ["149.90"]}
    with pytest.raises(WorkflowValidationError):
        collection_preview(book, Node(id="absent", action="core.map"), {})
