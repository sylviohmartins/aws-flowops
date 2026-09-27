from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge

from flowops.domain.models import Edge, Node
from flowops.streamlit.canvas import workflow_canvas
from flowops.streamlit.graph_layout import organize_workflow
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
            # React Flow creates edges without the Python adapter's deletion flags.
            browser[keys[-1]].edges.append(StreamlitFlowEdge("fresh", "start", "end"))
            connected, _ = workflow_canvas(accepted)
            assert len(connected.edges) == 3
            previous_key = keys[-1]
            refreshed, _ = workflow_canvas(connected)
            assert keys[-1] != previous_key
            assert browser[keys[-1]].edges[-1].deletable is True
            assert refreshed == connected
            stable_key = keys[-1]
            browser[stable_key].edges.pop()
            disconnected, _ = workflow_canvas(refreshed)
            assert len(disconnected.edges) == 2
            workflow_canvas(disconnected)
            assert keys[-1] == stable_key
            workflow_canvas(disconnected, readonly=True)
            assert all(not edge.deletable for edge in browser[keys[-1]].edges)


def test_organization_and_undo_replace_stale_browser_positions_without_losing_nodes() -> None:
    session: dict[str, Any] = {}
    browser: dict[str, Any] = {}
    keys: list[str] = []

    def component(key: str, state: Any, **kwargs: Any) -> Any:
        assert kwargs["fit_view"] is True and kwargs["min_zoom"] == 0.1
        keys.append(key)
        return browser.setdefault(key, state)

    book = blank("author", "ops")
    with patch.dict("sys.modules", {"streamlit": SimpleNamespace(session_state=session)}):
        with patch.object(streamlit_flow, "streamlit_flow", side_effect=component):
            initial, _ = workflow_canvas(book)
            organized, undo = organize_workflow(initial, 1)
            assert undo is not None
            accepted, _ = workflow_canvas(organized)
            assert accepted == organized and keys[-1] != keys[-2]
            restored, _ = workflow_canvas(undo.restore(accepted, 1))
            assert restored == initial and keys[-1] != keys[-2]
            workflow_canvas(restored)
            assert keys[-1] == keys[-2]
