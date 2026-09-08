"""Small trusted Streamlit v2 component for browser-local runbook copies."""

from __future__ import annotations

import json
from typing import Any

MAX_LOCAL_RECORD_BYTES = 250_000
MAX_LOCAL_RECORDS = 20

LOCAL_CATALOG_JS = r"""
export default function(component) {
  const { data, setStateValue } = component;
  const storageKey = `aws-flowops:catalog:${data.key}`;
  let records = [];
  try { records = JSON.parse(localStorage.getItem(storageKey) || "[]"); } catch (_) { records = []; }
  if (data.command === "save" && data.record) {
    const encoded = JSON.stringify(data.record);
    if (encoded.length <= 250000) {
      const next = records.filter((item) => item.id !== data.record.id);
      next.unshift(data.record);
      records = next.slice(0, 20);
    }
    localStorage.setItem(storageKey, JSON.stringify(records));
  } else if (data.command === "remove" && data.id) {
    records = records.filter((item) => item.id !== data.id);
    localStorage.setItem(storageKey, JSON.stringify(records));
  }
  setStateValue("records", records);
}
"""


def local_records(
    *,
    key: str,
    command: str = "",
    record: dict[str, Any] | None = None,
    record_id: str = "",
) -> list[dict[str, Any]]:
    """Return records from localStorage; gracefully degrade on older Streamlit versions."""
    import streamlit as st

    try:
        component = st.components.v2.component("flowops_browser_catalog", js=LOCAL_CATALOG_JS)
    except (AttributeError, ImportError):
        return st.session_state.get(f"flowops:local-catalog:{key}", [])
    state_key = f"flowops:browser-catalog:{key}"
    result = component(
        data={"key": key, "command": command, "record": record, "id": record_id},
        default={"records": []},
        key=state_key,
    )
    records = getattr(result, "records", None)
    if records is None and isinstance(result, dict):
        records = result.get("records")
    if not isinstance(records, list):
        state = st.session_state.get(state_key, {})
        records = state.get("records", []) if isinstance(state, dict) else []
    return [item for item in records if isinstance(item, dict)][:MAX_LOCAL_RECORDS]


def local_copy(book: Any) -> dict[str, Any]:
    return {
        "id": book.id,
        "name": book.name,
        "version": book.version,
        "body": book.model_dump(mode="json"),
    }


def local_copy_json(book: Any) -> str:
    return json.dumps(local_copy(book), ensure_ascii=False, separators=(",", ":"))
