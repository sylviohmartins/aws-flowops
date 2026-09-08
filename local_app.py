"""Personal emulator lab only. Production hosts keep their own authenticated bootstrap."""

import streamlit as st

from flowops.domain.models import Identity
from flowops.persistence.repository import Repository
from flowops.providers.aws.lab import LAB_DATABASE_URL
from flowops.providers.aws.local import local_context
from flowops.streamlit import FlowOpsPage

st.set_page_config(page_title="AWS FlowOps Local Lab", page_icon="◈", layout="wide")
st.caption("Laboratório local · Moto Server · recursos e credenciais de teste")
FlowOpsPage(
    user=Identity(id="local-operator", display_name="Operador local", roles=["ADMIN"]),
    aws_context=local_context(),
    repository=Repository(LAB_DATABASE_URL),
).render()
