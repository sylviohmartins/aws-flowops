from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import streamlit_flow

from flowops.domain.models import Edge, Node
from flowops.streamlit.canvas import workflow_canvas
from flowops.templates import blank


def test_stale_component_value_cannot_discard_external_edits() -> None:
    """Model the component's cached-return contract, including browser layout changes."""
    session: dict[str, Any] = {}
    browser: dict[str, Any] = {}
    keys: list[str] = []

    def component(key: str, state: Any, **kwargs: Any) -> Any:
        keys.append(key)
        return browser.setdefault(key, state)

    book = blank("author", "ops")
    with patch.dict("sys.modules", {"streamlit": SimpleNamespace(session_state=session)}):
        with patch.object(streamlit_flow, "streamlit_flow", side_effect=component):
            initial, _ = workflow_canvas(book)
            edited = initial.model_copy(deep=True)
            edited.nodes.insert(1, Node(id="lookup", action="dynamodb.get_item"))
            edited.edges = [
                Edge(source="start", target="lookup"),
                Edge(source="lookup", target="end"),
            ]
            accepted, _ = workflow_canvas(edited)
            assert [node.id for node in accepted.nodes] == ["start", "lookup", "end"]
            assert keys[0] != keys[1]
            accepted, _ = workflow_canvas(accepted)
            assert keys[1] == keys[2]
            assert accepted == edited
