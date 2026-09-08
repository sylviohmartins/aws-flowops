from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from flowops.domain.models import Runbook
from flowops.streamlit.browser_catalog import (
    LOCAL_CATALOG_JS,
    MAX_LOCAL_RECORDS,
    local_copy,
    local_copy_json,
)


def test_browser_catalog_is_bounded_local_storage_component_without_credentials() -> None:
    assert "localStorage" in LOCAL_CATALOG_JS
    assert "setStateValue" in LOCAL_CATALOG_JS
    assert str(MAX_LOCAL_RECORDS) in LOCAL_CATALOG_JS
    assert "secret" not in LOCAL_CATALOG_JS.lower()
    book = Runbook(name="XPTO", version=2)
    copy = local_copy(book)
    assert copy["id"] == book.id
    assert copy["version"] == 2
    assert '"body"' in local_copy_json(book)


def test_local_records_reads_component_state_and_falls_back_to_session_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flowops.streamlit.browser_catalog import local_records

    state = {"records": [{"id": "one"}, "invalid"]}

    class Component:
        def __call__(self, **kwargs: object) -> object:
            assert kwargs["data"]
            return SimpleNamespace(records=state["records"])

    component_streamlit = SimpleNamespace(
        components=SimpleNamespace(
            v2=SimpleNamespace(component=lambda *args, **kwargs: Component())
        ),
        session_state={},
    )
    monkeypatch.setitem(sys.modules, "streamlit", component_streamlit)
    assert local_records(key="component") == [{"id": "one"}]

    fallback_streamlit = SimpleNamespace(
        components=SimpleNamespace(),
        session_state={"flowops:local-catalog:fallback": [{"id": "fallback"}]},
    )
    monkeypatch.setitem(sys.modules, "streamlit", fallback_streamlit)
    assert local_records(key="fallback") == [{"id": "fallback"}]

    class EmptyComponent:
        def __call__(self, **kwargs: object) -> object:
            return SimpleNamespace(records=None)

    component_streamlit = SimpleNamespace(
        components=SimpleNamespace(
            v2=SimpleNamespace(component=lambda *args, **kwargs: EmptyComponent())
        ),
        session_state={"flowops:browser-catalog:empty": {"records": [{"id": "state"}]}},
    )
    monkeypatch.setitem(sys.modules, "streamlit", component_streamlit)
    assert local_records(key="empty") == [{"id": "state"}]
