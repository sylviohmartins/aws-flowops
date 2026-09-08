from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.domain.models import AWSContext, Identity
from flowops.streamlit import resource_picker

TABLE = {
    "TableName": "flowops-payments",
    "AttributeDefinitions": [
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "updatedAt", "AttributeType": "N"},
    ],
    "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "status-index",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
        }
    ],
}


class FakeStreamlit:
    def __init__(self, *, buttons: set[str] | None = None) -> None:
        self.buttons = buttons or set()
        self.session_state: dict[str, Any] = {}
        self.errors: list[str] = []
        self.reruns = 0

    def button(self, label: str, **kwargs: Any) -> bool:
        return label in self.buttons

    def dataframe(self, rows: Any, **kwargs: Any) -> None:
        pass

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        if label == "DynamoDB read":
            return "query"
        if label == "Index (optional)":
            return "status-index"
        if label == "Sort-key condition":
            return "between"
        if label == "Discovered resource":
            return options[0]
        return options[0]

    def text_input(self, label: str, **kwargs: Any) -> str:
        if "upper bound" in label:
            return "200"
        if "updatedAt" in label:
            return "100"
        return "PROCESSING"

    def number_input(self, label: str, **kwargs: Any) -> int:
        return 10

    def caption(self, value: str) -> None:
        pass

    def subheader(self, value: str) -> None:
        pass

    def info(self, value: str) -> None:
        pass

    def error(self, value: str) -> None:
        self.errors.append(value)

    def rerun(self) -> None:
        self.reruns += 1


class FakeUI:
    aws = AWSContext(mode="local")
    user = Identity(id="operator", permissions=["aws.read", "runbook.edit"])
    runtime = SimpleNamespace(registry=object())

    def __init__(self) -> None:
        self.stored: list[tuple[Any, int]] = []

    def _store_working(self, book: Any, revision: int) -> None:
        self.stored.append((book, revision))

    def _granted(self, permission: str, book: Any) -> bool:
        return permission == "runbook.edit"


def install_streamlit(monkeypatch: pytest.MonkeyPatch, fake: FakeStreamlit) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", fake)


def test_dynamodb_query_builder_ui_loads_schema_and_applies_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Load table schema", "Apply generated DynamoDB request"})
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(resource_picker, "read_action", lambda *args, **kwargs: {"Table": TABLE})
    ui = FakeUI()
    node = SimpleNamespace(config={}, action="dynamodb.query")
    book = SimpleNamespace(id="book")
    resource_picker._render_dynamodb_query(ui, book, node, 3, "flowops-payments", key="picker")
    assert node.config["IndexName"] == "status-index"
    assert node.config["Limit"] == 10
    assert node.config["ExpressionAttributeValues"][":end"] == {"N": "200"}
    assert ui.stored == [(book, 3)]
    assert fake.reruns == 1


def test_resource_picker_applies_discovered_queue_and_handles_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Discover resources for this node", "Apply discovered resource"})
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(
        resource_picker,
        "explore",
        lambda *args, **kwargs: {"QueueUrls": ["http://127.0.0.1:5000/queue"]},
    )
    ui = FakeUI()
    node = SimpleNamespace(id="node", action="sqs.send_message", config={})
    book = SimpleNamespace(id="book")
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert node.config["QueueUrl"].endswith("/queue")
    assert ui.stored == [(book, 1)]

    empty = FakeStreamlit()
    install_streamlit(monkeypatch, empty)
    no_resource = SimpleNamespace(id="node", action="s3.put_object", config={})
    resource_picker.render_resource_picker(ui, book, no_resource, 1)
    assert no_resource.config == {}
