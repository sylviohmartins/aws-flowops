"""Stable integration entrypoint. Importing this module never starts a server."""

from flowops.streamlit.integration import FlowOpsPage, render_flowops

__all__ = ["FlowOpsPage", "render_flowops"]
