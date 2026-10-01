import json

import pytest
from streamlit.testing.v1 import AppTest

from flowops.application import FlowOpsRuntime
from flowops.persistence.repository import Repository
from flowops.templates import dynamodb_query_lambda


@pytest.fixture
def runtime(tmp_path):
    result = FlowOpsRuntime.demo(Repository(tmp_path / "presenters.db"))
    yield result
    result.close()


BASE = """
import streamlit as st
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit.ui import FlowOpsUI
runtime = st.session_state["fixture-runtime"]
ui = FlowOpsUI(Identity(id="author",roles=["ADMIN"]),AWSContext(),runtime)
"""

WORKSPACE_BASE = """
import streamlit as st
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit.workspace import FlowOpsWorkspaceUI
runtime = st.session_state["fixture-runtime"]
ui = FlowOpsWorkspaceUI(Identity(id="author",roles=["ADMIN"]),AWSContext(),runtime)
"""


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def test_goal_wizard_validates_back_navigation_and_explicit_creation(runtime):
    app = AppTest.from_string(
        BASE
        + """
from flowops.streamlit.goal_wizard import render_goal_wizard
render_goal_wizard(ui)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    app.run()
    widget(app, "button", "Continuar").click().run()
    assert app.error and runtime.repository.list_runbooks() == []
    widget(app, "text_input", "Nome do novo fluxo").set_value("Jornada guiada")
    widget(app, "button", "Continuar").click().run()
    widget(app, "text_input", "Tabela a consultar").set_value("payments")
    widget(app, "text_input", "Valor da chave de partição").set_value("12345")
    widget(app, "button", "Continuar").click().run()
    widget(app, "button", "Voltar").click().run()
    assert widget(app, "text_input", "Tabela a consultar").value == "payments"
    widget(app, "button", "Continuar").click().run()
    widget(app, "checkbox", "Filtrar registros pelo status").set_value(True)
    widget(app, "button", "Continuar").click().run()
    widget(app, "text_input", "Função Lambda de destino").set_value("payment-processor")
    widget(app, "button", "Continuar").click().run()
    assert not app.exception and runtime.repository.list_runbooks() == []
    widget(app, "button", "Criar rascunho e abrir editor").click().run()
    books = runtime.repository.list_runbooks()
    assert len(books) == 1 and len(books[0].nodes) == 7
    assert app.session_state["flowops:next-page"] == "Editor"


def test_goal_wizard_can_select_discovered_aws_resources(runtime):
    app = AppTest.from_string(
        BASE
        + """
from flowops.streamlit.goal_wizard import render_goal_wizard
render_goal_wizard(ui)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    app.run()
    widget(app, "text_input", "Nome do novo fluxo").set_value("Recursos descobertos")
    widget(app, "button", "Continuar").click().run()

    widget(app, "button", "Buscar tabelas DynamoDB da conta").click().run()
    widget(app, "selectbox", "Tabela DynamoDB encontrada").set_value("payments")
    widget(app, "text_input", "Valor da chave de partição").set_value("12345")
    widget(app, "button", "Continuar").click().run()
    assert app.session_state["flowops:goal-wizard"]["values"]["table"] == "payments"

    widget(app, "button", "Continuar").click().run()
    widget(app, "button", "Buscar funções Lambda da conta").click().run()
    widget(app, "selectbox", "Função Lambda encontrada").set_value("payment-processor")
    widget(app, "button", "Continuar").click().run()
    assert app.session_state["flowops:goal-wizard"]["values"]["function"] == "payment-processor"
    assert not app.exception


def test_react_presenter_keeps_drafts_and_rejects_external_revision(runtime, monkeypatch):
    import streamlit.components.v1 as components

    payload = {}

    def component(**kwargs):
        data = kwargs["data"]
        return (
            None
            if not payload
            else {
                "protocol": 1,
                "book_id": data["book_id"],
                "revision": data["revision"],
                "base": data["base"],
                "event_id": "one",
                "kind": "draft",
                "operations": [],
            }
            | payload
        )

    monkeypatch.setattr(components, "declare_component", lambda *a, **kw: component)
    app = AppTest.from_string(
        BASE
        + """
from flowops.templates import dynamodb_query_lambda
from flowops.streamlit.react_editor import render_react_editor
book=dynamodb_query_lambda("author","default")
book.id="react-fixture"
working=ui._working_draft(book,1)
result,selected=render_react_editor(ui,working,1)
st.json(result.model_dump(mode="json"))
st.write(selected)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    app.run()
    assert not app.exception
    payload.update(kind="draft", operations=[{"op": "label", "node": "query", "value": "New name"}])
    app.run()
    assert app.session_state["flowops:react:react-fixture:pending"]["operations"]
    assert json.loads(app.json[-1].value)["nodes"][1]["label"] == "Consultar DynamoDB"
    payload.update(kind="apply", event_id="two")
    app.run()
    assert json.loads(app.json[-1].value)["nodes"][1]["label"] == "New name"
    assert "flowops:react:react-fixture:pending" not in app.session_state
    payload.update(kind="select", selected="query", operations=[], event_id="three")
    app.run()
    assert not app.exception
    payload.update(kind="draft", event_id="four", revision=3)
    app.run()
    assert app.error and not app.exception
    payload.pop("revision")
    payload.update(kind="draft", event_id="five")
    app.run()
    payload.update(kind="discard", event_id="six")
    app.run()
    assert "flowops:react:react-fixture:pending" not in app.session_state


def test_revision_conflict_preserves_and_exports_local_work(runtime):
    app = AppTest.from_string(
        BASE
        + """
from flowops.templates import dynamodb_query_lambda
from flowops.streamlit.edit_history import render_revision_conflict
book=dynamodb_query_lambda("author","default");book.id="conflict"
render_revision_conflict(ui,book,2)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    book = dynamodb_query_lambda("author", "default")
    book.name = "My preserved changes"
    app.session_state["flowops:working:conflict"] = {"revision": 1, "body": book.model_dump_json()}
    app.run()
    assert app.warning and not app.exception
    assert "My preserved changes" in app.session_state["flowops:working:conflict"]["body"]
    widget(app, "button", "Carregar revisão salva e descartar minhas edições").click().run()
    assert "flowops:working:conflict" not in app.session_state


def test_review_links_diagnostics_to_nodes_without_operational_calls(runtime):
    app = AppTest.from_string(
        BASE
        + """
from flowops.templates import dynamodb_query_lambda
from flowops.streamlit.authoring_review import render_review
book=dynamodb_query_lambda("author","default");book.id="review"
book.nodes[1].config={}
render_review(ui,book,1)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    app.run()
    assert app.warning and not app.exception
    widget(app, "button", "Corrigir Consultar DynamoDB").click().run()
    assert app.session_state["flowops:pending-node:review"] == "query"
    widget(app, "button", "Abrir execução de versão publicada").click().run()
    assert app.session_state["flowops:next-page"] == "Execute"
    assert runtime.repository.list_runbooks() == []


def test_applied_history_undo_redo_keeps_selection_and_parameter_values(runtime):
    app = AppTest.from_string(
        BASE
        + """
from flowops.templates import dynamodb_query_lambda
from flowops.streamlit.edit_history import render_history
book=dynamodb_query_lambda("author","default");book.id="history"
working=ui._working_draft(book,1)
render_history(ui,working,1)
if st.button("Alterar"):
    working.nodes[1].config["Limit"]=5
    ui._store_working(working,1)
    st.rerun()
st.json(working.nodes[1].config)
"""
    )
    app.session_state["fixture-runtime"] = runtime
    app.run()
    widget(app, "button", "Alterar").click().run()
    assert json.loads(app.json[-1].value)["Limit"] == 5
    widget(app, "button", "Desfazer edição").click().run()
    assert json.loads(app.json[-1].value)["Limit"] == 30
    widget(app, "button", "Refazer edição").click().run()
    assert json.loads(app.json[-1].value)["Limit"] == 5


def test_editor_keeps_assistant_and_selected_node_after_undo_redo(runtime):
    book = dynamodb_query_lambda("author", "default")
    runtime.repository.save_draft(book, "author")
    app = AppTest.from_string(WORKSPACE_BASE + "ui._editor()", default_timeout=30)
    app.session_state["fixture-runtime"] = runtime
    app.run()
    app.radio(key=f"flowops:editor-view:{book.id}").set_value("Assistente").run()
    app.selectbox(key=f"flowops:node:{book.id}").set_value("invoke").run()
    widget(app, "text_input", "Nome da etapa").set_value("Envio revisado")
    widget(app, "button", "Aplicar propriedades da etapa").click().run()
    for label in ("Desfazer edição", "Refazer edição"):
        widget(app, "button", label).click().run()
        assert not app.exception
        assert app.radio(key=f"flowops:editor-view:{book.id}").value == "Assistente"
        assert app.selectbox(key=f"flowops:node:{book.id}").value == "invoke"
        assert any(item.label == "Próxima etapa" for item in app.button)


def test_history_uses_fresh_widget_generation_for_restored_parameter_binding(runtime):
    from flowops.streamlit.authoring import EditBuffer

    book = dynamodb_query_lambda("author", "default")
    next(node for node in book.nodes if node.id == "invoke").config["Payload"]["source"] = "flowops"
    runtime.repository.save_draft(book, "author")
    app = AppTest.from_string(WORKSPACE_BASE + "ui._editor()", default_timeout=30)
    app.session_state["fixture-runtime"] = runtime
    app.run()
    app.radio(key=f"flowops:editor-view:{book.id}").set_value("Assistente").run()
    app.selectbox(key=f"flowops:node:{book.id}").set_value("invoke").run()
    widget(app, "text_input", "Nome do parâmetro de source").set_value("source_system")
    widget(app, "checkbox", "Usar valor atual de source como padrão").set_value(True)
    widget(app, "button", "Preparar parâmetro e vínculo de source").click().run()
    widget(app, "button", "Aplicar configuração ao rascunho").click().run()
    key = f"flowops:visual:{book.id}:invoke:lambda.invoke"
    previous = app.session_state[key]
    for label in ("Desfazer edição", "Refazer edição"):
        widget(app, "button", label).click().run()
        current = app.session_state[key]
        assert isinstance(current, EditBuffer) and current.epoch > previous.epoch
        previous = current
    assert current.value["Payload"]["source"] == "{{ params.source_system }}"
    widget(app, "text_input", "Nome do novo campo em Dados enviados à função (Payload)").set_value(
        "origin"
    ).run()
    widget(app, "button", "Adicionar campo em Dados enviados à função (Payload)").click().run()
    widget(app, "text_input", "origin").set_value("web").run()
    widget(app, "button", "Aplicar configuração ao rascunho").click().run()
    assert not app.exception
    body = json.loads(app.session_state[f"flowops:working:{book.id}"]["body"])
    assert body["parameters"]["source_system"]["default"] == "flowops"
    invoke = next(node for node in body["nodes"] if node["id"] == "invoke")
    assert invoke["config"]["Payload"]["origin"] == "web"
    assert invoke["config"]["Payload"]["source"] == "{{ params.source_system }}"
