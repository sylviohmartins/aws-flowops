from types import SimpleNamespace

from flowops.streamlit.results import render_results
from tests.test_results import FakeResultUI


def test_late_live_fragment_cannot_render_after_navigation(monkeypatch) -> None:
    """Replay a timer registered on Execute after a navigation value was received."""
    import sys

    from flowops.streamlit.live_execution import render_live_execution

    fake = FakeResultUI()
    fake.session_state["flowops:navigation"] = "Execute"
    callbacks = []
    fake.fragment = lambda **kwargs: lambda view: lambda: callbacks.append(view)

    monkeypatch.setitem(sys.modules, "streamlit", fake)
    # The stale callback must not read/render results, much less submit anything.
    ui = SimpleNamespace(runtime=None)
    render_live_execution(ui, "late-timer")
    fake.session_state["flowops:navigation"] = "Approvals"
    callbacks[0]()


def test_transient_canvas_remount_must_not_reapply_old_selection(monkeypatch) -> None:
    import sys

    fake = FakeResultUI()
    fake.selectbox = lambda label, options, **kwargs: fake.session_state.get(
        kwargs["key"], options[0]
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    execution = SimpleNamespace(id="remount", snapshot=SimpleNamespace(nodes=[]))
    details = {"query": {"output": []}, "invoke": {"output": {"done": True}}}
    render_results(execution, details, selected_node="query")
    # Keyboard selection is independent of the last canvas click.
    fake.session_state["flowops:results:remount:node"] = "invoke"
    render_results(execution, details, selected_node=None)
    render_results(execution, details, selected_node="query")
    assert fake.session_state["flowops:results:remount:node"] == "invoke"
