"""Scoped presentation styles shared by standalone and embedded workspaces."""

from pathlib import Path


def render_workspace_style() -> None:
    import streamlit as st

    st.html(Path(__file__).with_name("workspace.css"))
