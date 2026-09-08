from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from flowops.streamlit.results import result_rows


def test_result_rows_decodes_dynamodb_envelopes_and_bounds_rows() -> None:
    rows = result_rows(
        {
            "Items": [
                {
                    "paymentId": {"S": "PAY-1"},
                    "amount": {"N": "149.90"},
                    "details": {"M": {"active": {"BOOL": True}}},
                }
            ]
        },
        "dynamodb.query",
    )
    assert rows == [{"paymentId": "PAY-1", "amount": "149.90", "details": '{"active": true}'}]
    assert result_rows({"_truncated": True}, "dynamodb.scan") == []


def test_result_rows_handles_scalar_and_nested_provider_outputs() -> None:
    assert result_rows({"Payload": {"event": {"id": "1"}}}, "lambda.invoke") == [
        {"event": '{"id": "1"}'}
    ]
    assert result_rows(["a", "b"]) == [{"value": "a"}, {"value": "b"}]
    assert result_rows(
        {
            "Item": {
                "empty": {"NULL": True},
                "list": {"L": [{"S": "one"}]},
                "unknown": {"X": "value"},
                "multiple": {"S": "one", "N": "1"},
            }
        },
        "dynamodb.get_item",
    ) == [
        {
            "empty": None,
            "list": '["one"]',
            "unknown": '{"X": "value"}',
            "multiple": '{"S": "one", "N": "1"}',
        }
    ]


def test_render_output_and_results_use_explicit_table_json_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flowops.streamlit.results import render_output, render_results

    class FakeStreamlit:
        def __init__(self) -> None:
            self.frames: list[object] = []
            self.downloads: list[str] = []

        def radio(self, label: str, options: list[str], **kwargs: object) -> str:
            return "Table"

        def dataframe(self, rows: object, **kwargs: object) -> None:
            self.frames.append(rows)

        def caption(self, value: str) -> None:
            pass

        def json(self, value: object, **kwargs: object) -> None:
            self.frames.append(value)

        def download_button(self, label: str, data: str, **kwargs: object) -> None:
            self.downloads.append(data)

        def subheader(self, value: str) -> None:
            pass

        def selectbox(self, label: str, options: list[str], **kwargs: object) -> str:
            return options[0]

    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    render_output({"Items": [{"id": {"S": "1"}}]}, action="dynamodb.query", key="result")
    assert fake.frames
    assert fake.downloads

    execution = SimpleNamespace(
        id="exec",
        snapshot=SimpleNamespace(
            nodes=[SimpleNamespace(id="node", action="dynamodb.query", config={})]
        ),
    )
    render_results(execution, {"node": {"output": {"Items": [{"id": {"S": "1"}}]}}})
    assert len(fake.frames) == 2

    fake.radio = lambda label, options, **kwargs: "JSON"
    render_output({"value": 1}, action="", key="json-result")
    assert fake.frames[-1] == {"value": 1}
    render_results(execution, {})
