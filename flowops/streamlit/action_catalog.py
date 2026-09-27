"""Search installed SDK metadata without making AWS calls or granting capabilities."""

from typing import Any

from flowops.providers.aws.catalog import BLOCKED_SERVICES, ModelCatalog
from flowops.providers.aws.demo import SUPPORTED
from flowops.streamlit.localization import display, schema_view


def _open_editor(action_id: str) -> None:
    import streamlit as st

    st.session_state["flowops:catalog-action"] = action_id
    st.session_state["flowops:navigation"] = "Editor"


def render_catalog(ui: Any) -> None:
    import streamlit as st

    st.header("Catálogo de ações AWS")
    registered = {item.id: item for item in ui.runtime.registry.list()}
    catalog = ModelCatalog()
    services = catalog.services()
    st.caption(
        f"{len(registered)} ações habilitadas · {len(services)} serviços no SDK instalado. "
        "Consultar estruturas de dados não faz chamadas à AWS."
    )
    filters = st.columns(2)
    service = filters[0].selectbox("Serviço AWS", services, index=services.index("dynamodb"))
    search = filters[1].text_input("Buscar operação", help="Ex.: query, invoke, describe ou start")
    operations = [name for name in catalog.operations(service) if search.lower() in name.lower()]
    if not operations:
        st.info("Nenhuma operação corresponde à busca.")
        return
    operation = st.selectbox("Operação AWS", sorted(operations))
    action_id = f"{service}.{operation}"
    metadata = registered.get(action_id)
    if metadata:
        st.success(f"Disponível no editor: {action_id}")
        st.write(
            f"Risco: {display(metadata.risk.value)} · somente leitura: {display(metadata.read_only)} · "
            f"idempotente: {display(metadata.idempotent)}"
        )
        st.code(", ".join(metadata.required_permissions), language=None)
        if ui.aws.mode == "demo" and action_id not in SUPPORTED:
            st.warning(
                "O catálogo conhece esta ação, mas o modo de demonstração não a executa. Use um contexto AWS configurado ou um laboratório compatível."
            )
        st.button(
            "Usar no editor",
            disabled=not ui._granted("runbook.edit"),
            on_click=_open_editor,
            args=(action_id,),
        )
    elif service in BLOCKED_SERVICES:
        st.warning(
            "Serviço sensível bloqueado para ações genéricas. Consultar o modelo não habilita execução."
        )
    else:
        st.info(
            "Modelo disponível para consulta. Esta operação ainda não está habilitada pela aplicação hospedeira; operações genéricas exigem uma lista de permissões explícita e têm risco conservador."
        )
    model = catalog.operation(service, operation)
    input_schema = metadata.input_schema if metadata else catalog.schema(model.input_shape)
    output_schema = metadata.output_schema if metadata else catalog.schema(model.output_shape)
    left, right = st.columns(2)
    with left:
        st.subheader("Entrada")
        st.json(schema_view(input_schema))
    with right:
        st.subheader("Saída")
        st.json(schema_view(output_schema, "saída"))
    with st.expander("Referência técnica original do SDK", expanded=False):
        st.caption("Documentação original do fornecedor, preservada para consulta técnica.")
        st.json({"entrada": input_schema, "saída": output_schema}, expanded=False)
