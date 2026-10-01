import pytest
from streamlit.testing.v1 import AppTest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Node, Runbook
from flowops.streamlit.flow_journey import branch_options, connect, ordered_nodes
from flowops.templates import dynamodb_query_lambda
from tests.app_test_support import close_app_runtime


def test_keyboard_connections_preserve_graph_and_reject_unsafe_topology() -> None:
    book = dynamodb_query_lambda("author", "default")
    original = book.model_copy(deep=True)
    result = connect(book, "query", "end", "default")
    assert book == original and len(result.edges) == len(book.edges) + 1
    assert ordered_nodes(book)[0] == "start" and ordered_nodes(book)[-1] == "end"
    for source, target, branch in (
        ("missing", "end", "default"),
        ("query", "query", "default"),
        ("end", "query", "default"),
        ("query", "start", "default"),
        ("query", "approve", "invalid"),
        ("start", "query", "default"),
        ("invoke", "query", "default"),
    ):
        with pytest.raises(WorkflowValidationError):
            connect(book, source, target, branch)
    book.edges.append(Edge(source="start", target="unknown"))
    with pytest.raises(WorkflowValidationError):
        ordered_nodes(book)
    book = Runbook(
        name="Branches",
        nodes=[
            Node(id="condition", action="core.condition", failure_policy="FAIL_BRANCH"),
            Node(id="switch", action="core.switch", config={"cases": {"match": 1}}),
        ],
    )
    assert branch_options(book, "condition") == ["true", "false", "failure"]
    assert branch_options(book, "switch") == ["default", "match"]


def test_connections_real_widgets_apply_only_explicitly_and_preserve_branch(monkeypatch) -> None:
    script = """
from types import SimpleNamespace
import streamlit as st
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit.ui import FlowOpsUI
from flowops.streamlit.flow_journey import render_connections
from flowops.templates import dynamodb_query_lambda
ui = FlowOpsUI(Identity(id="author", roles=["ADMIN"]), AWSContext(), SimpleNamespace(repository=None))
book = dynamodb_query_lambda("author", "default")
book.id = "connections"
working = ui._working_draft(book, 1)
render_connections(ui, working, 1)
st.json([edge.model_dump() for edge in working.edges])
"""
    app = AppTest.from_string(script).run()
    before = app.json[0].value
    app.selectbox[0].set_value("query").run()
    app.selectbox[1].set_value("end").run()
    assert app.json[0].value == before
    app.button[0].click().run()
    assert not app.exception and app.json[0].value != before
    app.button[0].click().run()
    assert app.error and not app.exception
    app.selectbox[-1].set_value(5).run()
    app.button[-1].click().run()
    assert app.json[0].value == before


def test_assistant_and_list_share_same_session_draft(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from flowops.persistence.repository import Repository

    monkeypatch.setenv("FLOWOPS_DATABASE", str(tmp_path / "guide.db"))
    monkeypatch.delenv("FLOWOPS_DATABASE_URL", raising=False)
    repo = Repository(tmp_path / "guide.db")
    book = dynamodb_query_lambda("demo-author", "default")
    repo.save_draft(book, "demo-author")
    original = repo.get_draft(book.id)
    app = AppTest.from_file(Path(__file__).parents[1] / "standalone_app.py").run(timeout=30)

    def widget(kind, label):
        return next(w for w in getattr(app, kind) if w.label == label)

    try:
        app.sidebar.radio[0].set_value("Editor").run(timeout=30)
        widget("radio", "Visão de edição").set_value("Lista de etapas").run(timeout=30)
        assert not app.exception
        widget("selectbox", "Propriedades da etapa").set_value("prepare_event").run(timeout=30)
        widget("radio", "Visão de edição").set_value("Assistente").run(timeout=30)
        assert not app.exception
        assert widget("radio", "Modo de configuração").value == "Visual"
        widget("button", "Prévia fictícia da transformação").click().run(timeout=30)
        assert any('"12345"' in entry.value for entry in app.json)
        from tests.test_visual_authoring import widget as keyed_widget

        keyed_widget(app, "selectbox", ':["template", "payment_id"]:kind').set_value("string").run(
            timeout=30
        )
        keyed_widget(app, "text_input", ':["template", "payment_id"]:value').set_value(
            "pending-value"
        ).run(timeout=30)
        assert widget("button", "Salvar rascunho").disabled
        assert widget("button", "Publicar versão").disabled
        widget("button", "Prévia fictícia da transformação").click().run(timeout=30)
        assert any("pending-value" in entry.value for entry in app.json)
        widget("button", "Aplicar configuração ao rascunho").click().run(timeout=30)
        assert not widget("button", "Salvar rascunho").disabled
        widget("button", "Próxima etapa").click().run(timeout=30)
        assert widget("selectbox", "Propriedades da etapa").value == "approve"
        widget("button", "Etapa anterior").click().run(timeout=30)
        assert widget("selectbox", "Propriedades da etapa").value == "prepare_event"
        # The assistant must own the AWS editor even without a previously open dialog.
        app.session_state[f"flowops:node-dialog:{book.id}"] = None
        widget("selectbox", "Propriedades da etapa").set_value("query").run(timeout=30)
        assert not app.exception
        assert len([w for w in app.radio if w.label == "Modo de configuração"]) == 1
        assert repo.get_draft(book.id) == original
    finally:
        close_app_runtime(app, repo)
