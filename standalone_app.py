"""Standalone bootstrap only. Corporate hosts import FlowOpsPage instead."""

import os

import streamlit as st

from flowops.domain.models import AWSContext, Identity
from flowops.persistence.repository import Repository
from flowops.streamlit import FlowOpsPage

st.set_page_config(page_title="AWS FlowOps Studio", page_icon="◈", layout="wide")
FlowOpsPage(
    Identity(id="demo-author", display_name="Operador demo", roles=["ADMIN"]),
    AWSContext(),
    repository=Repository(os.getenv("FLOWOPS_DATABASE", "flowops.db")),
).render()
