"""Narrow fixed-label adapter for third-party Streamlit/React Flow controls."""

from pathlib import Path


def render_component_locale() -> None:
    import streamlit as st

    component = st.components.v2.component(
        "flowops_pt_br", js=Path(__file__).with_name("ui_locale.js").read_text(encoding="utf-8")
    )
    component(key="flowops:pt-br")
