"""Standalone bootstrap only. Corporate hosts import FlowOpsPage instead."""

import streamlit as st

from flowops.domain.models import AWSContext, Identity
from flowops.identity import StaticIdentityProvider
from flowops.streamlit import FlowOpsPage

st.set_page_config(page_title="AWS FlowOps Studio", page_icon="◈", layout="wide")
identity_provider = StaticIdentityProvider(
    Identity(id="demo-author", display_name="Operador demo", roles=["ADMIN"])
)
FlowOpsPage(identity_provider.current(), AWSContext()).render()
