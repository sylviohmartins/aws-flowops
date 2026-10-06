import sys
from types import SimpleNamespace

from flowops.domain.models import Node, Runbook
from flowops.streamlit.authoring import EditBuffer


def test_delayed_mode_callback_after_undo_cannot_access_deleted_keys(monkeypatch):
    from flowops.streamlit import value_editor

    callbacks = []
    state = {}
    node = Node(id="typed", action="test.typed", config={"name": "old"})
    book = Runbook(id="history-callback", name="History", nodes=[node])
    key = f"flowops:visual:{book.id}:{node.id}:{node.action}"
    original = EditBuffer.create(node.config)
    state[key] = original

    def radio(*args, **kwargs):
        callbacks.append(kwargs["on_change"])
        state[kwargs["key"]] = "Visual"

    fake = SimpleNamespace(
        session_state=state,
        subheader=lambda *a: None,
        caption=lambda *a: None,
        radio=radio,
        button=lambda *a, **kw: False,
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(value_editor, "_tree", lambda *a, **kw: None)
    ui = SimpleNamespace(_granted=lambda *a: True, runtime=SimpleNamespace(registry=None))
    value_editor.render_config_editor(ui, book, node, 1, {})
    state.pop(key + ":mode")
    callbacks[0]()
    state[key] = EditBuffer.create(node.config)
    state[key + ":mode"] = "Ver JSON"
    callbacks[0]()
    assert original.mode == "Visual" and state[key].mode == "Visual"
