from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from flowops.application import FlowOpsRuntime
from flowops.core.actions import ActionContext
from flowops.core.engine import Engine
from flowops.core.policies import PolicyEngine
from flowops.domain.errors import ProviderError
from flowops.domain.models import AWSContext, Edge, Identity, Status
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import AWSAction, build_registry
from flowops.providers.aws.catalog import SPECS, ModelCatalog
from flowops.providers.aws.demo import DemoBackend
from flowops.providers.aws.query_builder import build_read
from flowops.streamlit.canvas import edge_visual
from flowops.streamlit.results import result_csv
from flowops.templates import dynamodb_query_lambda


@pytest.mark.parametrize("simulation", [True, False])
def test_query_map_approval_lambda_reference(tmp_path: Path, simulation: bool) -> None:
    repo = Repository(tmp_path / "reference.db")
    backend = DemoBackend(repo)
    engine = Engine(
        repo, build_registry(backend, catalog=ModelCatalog()), policy=PolicyEngine(two_person=False)
    )
    book = dynamodb_query_lambda("author", "default")
    revision = repo.save_draft(book, "author")
    published = repo.publish(book.id, "author", revision)
    actor = Identity(id="operator", roles=["ADMIN"])
    execution = engine.submit(
        published, actor, AWSContext(), {}, token="reference", dry_run=simulation
    )
    result = engine.execute(execution.id)
    if simulation:
        assert result.status == Status.SUCCESS
        assert engine.store.pending_approvals() == []
        assert result.node_outputs["approve"]["approval_required_live"]
    else:
        assert result.status == Status.WAITING_APPROVAL
        pending = engine.store.pending_approvals()[0]
        engine.approve(
            result.id,
            pending["node_id"],
            pending["digest"],
            actor,
            approved=True,
            reason="Reviewed demo payload",
        )
        result = engine.execute(result.id)
        assert result.status == Status.SUCCESS
        assert result.node_outputs["invoke"]["Payload"]["payload"]["payments"] == [
            {"payment_id": "12345", "status": "PROCESSING"}
        ]
    assert result.node_outputs["query"]["Count"] == 1
    assert result.node_outputs["prepare_event"]["items"][0]["payment_id"] == "12345"
    assert repo.version(book.id, 1) == published


def test_generated_query_is_supported_in_demo(tmp_path: Path) -> None:
    backend = DemoBackend(Repository(tmp_path / "query.db"))
    catalog = ModelCatalog()
    context = ActionContext("test", "query", AWSContext(), False)
    table = AWSAction(SPECS["dynamodb.describe_table"], backend, catalog).execute(
        {"TableName": "payments"}, context
    )["Table"]
    query = AWSAction(SPECS["dynamodb.query"], backend, catalog)
    result = query.execute(build_read("query", table, {"paymentId": "23456"}), context)
    assert [item["paymentId"]["S"] for item in result["Items"]] == ["23456"]
    with pytest.raises(ProviderError, match="paymentId equality"):
        query.execute(
            {
                "TableName": "payments",
                "KeyConditionExpression": "other = :x",
                "ExpressionAttributeValues": {":x": {"S": "12345"}},
            },
            context,
        )


def test_live_edges_follow_selected_branch_and_terminal_states() -> None:
    edge = Edge(source="condition", target="task", branch="true")
    statuses = {"condition": "SUCCESS", "task": "RUNNING"}
    assert edge_visual(edge, statuses, {"condition": "true"})["animated"]
    assert not edge_visual(edge, statuses, {"condition": "false"})["animated"]
    assert edge_visual(edge, statuses, {"condition": "false"})["style"]["stroke"] == "#cbd5e1"
    for status, color in [
        ("SUCCESS", "#15803d"),
        ("FAILED", "#dc2626"),
        ("WAITING_APPROVAL", "#b45309"),
    ]:
        style = edge_visual(edge, statuses | {"task": status}, {"condition": "true"})
        assert style["style"]["stroke"] == color
        assert not style["animated"]
    assert edge_visual(
        Edge(source="a", target="b", branch="failure"),
        {"a": "FAILED", "b": "RUNNING"},
        {"a": "failure"},
    )["animated"]


def test_export_neutralizes_formulas_in_headers_and_values() -> None:
    csv = result_csv([{"=HEADER": '=HYPERLINK("example")', "value": "  @SUM(1)", "count": 3}])
    assert "'=HEADER" in csv
    assert "'=HYPERLINK" in csv
    assert "'  @SUM" in csv
    assert ",3" in csv


def test_new_aws_metadata_and_partial_failures() -> None:
    class Backend:
        def invoke(self, *args: object) -> dict:
            return {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "AccessDeniedException"}]}

    catalog = ModelCatalog()
    action = AWSAction(SPECS["events.put_events"], Backend(), catalog)
    with pytest.raises(ProviderError, match="PartialFailure"):
        action.execute(
            {"Entries": [{"Source": "test", "DetailType": "test", "Detail": "{}"}]},
            ActionContext("e", "n", AWSContext(), False),
        )
    ec2 = AWSAction(SPECS["ec2.stop_instances"], Backend(), catalog)
    assert not ec2.metadata.idempotent and not ec2.metadata.read_only
    assert ec2.affected_records({"InstanceIds": ["i-123", "i-456"]}) == 2
    assert AWSAction(
        SPECS["stepfunctions.start_execution"], Backend(), catalog
    ).metadata.required_permissions == ("states:StartExecution",)
    assert AWSAction(
        SPECS["elbv2.describe_target_health"], Backend(), catalog
    ).metadata.required_permissions == ("elasticloadbalancing:DescribeTargetHealth",)


def test_guide_catalog_and_node_dialog_do_not_persist_on_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "ui.db"
    monkeypatch.setenv("FLOWOPS_DATABASE", str(database))
    monkeypatch.delenv("FLOWOPS_DATABASE_URL", raising=False)
    repo = Repository(database)
    book = dynamodb_query_lambda("demo-author", "default")
    repo.save_draft(book, "demo-author")
    before = repo.get_draft(book.id)
    app = AppTest.from_file(Path(__file__).parents[1] / "standalone_app.py").run(timeout=30)
    try:
        for page in ["Guide", "Catalog", "Editor"]:
            app.sidebar.radio[0].set_value(page).run(timeout=30)
            assert not app.exception
        next(
            widget for widget in app.selectbox if widget.label == "Propriedades da etapa"
        ).set_value("query").run(timeout=30)
        next(
            widget for widget in app.button if widget.label == "Editar etapa selecionada"
        ).click().run(timeout=30)
        assert not app.exception
        next(widget for widget in app.radio if widget.label == "Modo de configuração").set_value(
            "Editar JSON"
        ).run(timeout=30)
        config = next(
            widget for widget in app.text_area if widget.label == "Código JSON da configuração"
        )
        value = json.loads(config.value)
        value["Limit"] = 5
        config.set_value(json.dumps(value))
        next(
            widget for widget in app.button if widget.label == "Aplicar configuração ao rascunho"
        ).click().run(timeout=30)
        assert not app.exception
        assert repo.get_draft(book.id) == before
        next(widget for widget in app.button if widget.label == "Voltar ao fluxo").click().run(
            timeout=30
        )
        next(widget for widget in app.button if widget.label == "Salvar rascunho").click().run(
            timeout=30
        )
        assert not app.exception
        saved, revision = repo.get_draft(book.id)
        assert revision == 2
        assert next(node for node in saved.nodes if node.id == "query").config["Limit"] == 5
        next(
            widget for widget in app.button if widget.label == "Editar etapa selecionada"
        ).click().run(timeout=30)
        next(
            widget for widget in app.button if widget.label == "Duplicar etapa selecionada"
        ).click().run(timeout=30)
        copied_id = next(
            widget for widget in app.selectbox if widget.label == "Propriedades da etapa"
        ).value
        assert copied_id != "query"
        assert app.session_state[f"flowops:node-dialog:{book.id}"] == copied_id
        assert not app.exception
        next(
            widget for widget in app.button if widget.label == "Remover etapa selecionada"
        ).click().run(timeout=30)
        assert not app.exception
        assert f"flowops:node-dialog:{book.id}" not in app.session_state.filtered_state
        assert repo.get_draft(book.id)[1] == 2
    finally:
        for value in app.session_state.filtered_state.values():
            if isinstance(value, FlowOpsRuntime):
                value.close()


def test_logic_dialog_validation_catalog_filters_and_two_person_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "logic-ui.db"
    monkeypatch.setenv("FLOWOPS_DATABASE", str(database))
    monkeypatch.delenv("FLOWOPS_DATABASE_URL", raising=False)
    repo = Repository(database)
    book = dynamodb_query_lambda("demo-author", "default")
    repo.save_draft(book, "demo-author")
    app = AppTest.from_file(Path(__file__).parents[1] / "standalone_app.py").run(timeout=30)

    def widget(kind, label):
        return next(item for item in getattr(app, kind) if item.label == label)

    try:
        app.sidebar.radio[0].set_value("Editor").run(timeout=30)
        widget("selectbox", "Propriedades da etapa").set_value("prepare_event").run(timeout=30)
        widget("button", "Editar etapa selecionada").click().run(timeout=30)
        widget("radio", "Modo de configuração").set_value("Editar JSON").run(timeout=30)
        original = widget("text_area", "Código JSON da configuração").value
        widget("text_area", "Código JSON da configuração").set_value("not JSON")
        widget("button", "Aplicar configuração ao rascunho").click().run(timeout=30)
        assert not app.exception and any("JSON inválido" in item.value for item in app.error)
        widget("text_area", "Código JSON da configuração").set_value(original)
        widget("button", "Aplicar configuração ao rascunho").click().run(timeout=30)
        assert not app.exception
        widget("button", "Voltar ao fluxo").click().run(timeout=30)
        widget("selectbox", "Propriedades da etapa").set_value("approve").run(timeout=30)
        widget("button", "Editar etapa selecionada").click().run(timeout=30)
        assert any("aprovação é simulada" in item.value for item in app.info)
        widget("button", "Voltar ao fluxo").click().run(timeout=30)
        widget("selectbox", "Serviço da ação").set_value("core").run(timeout=30)
        widget("text_input", "Buscar ação").set_value("no-matching-action").run(timeout=30)
        assert not app.exception
        assert widget("button", "Inserir antes do fim").disabled
        assert widget("selectbox", "Propriedades da etapa")
        app.sidebar.radio[0].set_value("Catalog").run(timeout=30)
        widget("selectbox", "Serviço AWS").set_value("ec2").run(timeout=30)
        widget("text_input", "Buscar operação").set_value("describe_instances").run(timeout=30)
        assert any("modo de demonstração não" in item.value for item in app.warning)
        widget("button", "Usar no editor").click().run(timeout=30)
        assert not app.exception
        assert widget("selectbox", "Ação").value == "ec2.describe_instances"
        assert widget("text_input", "Buscar ação").value == ""
        assert widget("selectbox", "Serviço da ação").value == "All"
        app.sidebar.radio[0].set_value("Catalog").run(timeout=30)
        widget("text_input", "Buscar operação").set_value("no-match").run(timeout=30)
        assert any("Nenhuma operação" in item.value for item in app.info)
        widget("text_input", "Buscar operação").set_value("").run(timeout=30)
        widget("selectbox", "Serviço AWS").set_value("iam").run(timeout=30)
        assert any("Serviço sensível bloqueado" in item.value for item in app.warning)
        widget("selectbox", "Serviço AWS").set_value("ec2").run(timeout=30)
        widget("text_input", "Buscar operação").set_value("describe_hosts").run(timeout=30)
        assert any("lista de permissões explícita" in item.value for item in app.info)
        assert repo.get_draft(book.id)[1] == 1
        runtime = next(
            value
            for value in app.session_state.filtered_state.values()
            if isinstance(value, FlowOpsRuntime)
        )
        published = repo.publish(book.id, "demo-author", 1)
        actor = Identity(id="demo-author", roles=["ADMIN"])
        execution = runtime.engine.submit(
            published, actor, AWSContext(), {}, token="two-person", dry_run=False
        )
        assert runtime.engine.execute(execution.id).status == Status.WAITING_APPROVAL
        runtime.engine.policy = PolicyEngine(two_person=True)
        app.sidebar.radio[0].set_value("Approvals").run(timeout=30)
        assert not app.exception
        assert widget("button", "Aprovar").disabled and widget("button", "Rejeitar").disabled
        assert any("outra pessoa" in item.value for item in app.warning)
    finally:
        for value in app.session_state.filtered_state.values():
            if isinstance(value, FlowOpsRuntime):
                value.close()


@pytest.mark.parametrize("status", [Status.WAITING_APPROVAL, Status.FAILED, Status.SUCCESS])
def test_live_view_reads_fresh_checkpoint_and_exports_failed_node(
    monkeypatch: pytest.MonkeyPatch, status: Status
) -> None:
    from flowops.streamlit import live_execution
    from tests.test_results import FakeResultUI

    fake = FakeResultUI()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    book = dynamodb_query_lambda("operator", "default")
    execution = SimpleNamespace(
        id="live",
        status=status,
        snapshot=book,
        error="query failed" if status == Status.FAILED else None,
        dry_run=status == Status.SUCCESS,
    )
    checkpoints = {"query": {"status": status.value, "output": None, "error": execution.error}}
    store = SimpleNamespace(get=lambda key: execution, nodes=lambda key: checkpoints)
    ui = SimpleNamespace(
        user=Identity(id="operator", roles=["ADMIN"]),
        runtime=SimpleNamespace(engine=SimpleNamespace(store=store)),
    )
    canvas_calls = []

    def canvas(book, **kwargs):
        canvas_calls.append(kwargs)
        return book, "query"

    monkeypatch.setattr(live_execution, "workflow_canvas", canvas)
    live_execution.render_live_execution(ui, "live")
    assert canvas_calls[-1]["statuses"]["query"] == status.value
    assert fake.session_state["flowops:results:live:node"] == "query"
    assert json.loads(fake.downloads[-1])["status"] == status.value
    if status == Status.FAILED:
        assert fake.errors == [
            "Não foi possível concluir a operação. Consulte os detalhes técnicos para identificar a causa."
        ]
        assert "query failed" in fake.frames
    if status == Status.WAITING_APPROVAL:
        assert any("Execução pausada" in text for text in fake.warnings)
    if status == Status.SUCCESS:
        assert any("Simulação" in text for text in fake.infos)


def test_logic_fields_cannot_partially_apply_or_bypass_permissions() -> None:
    from flowops.streamlit.node_editor import initial_config
    from tests.test_visual_authoring import SCRIPT, widget

    # Exercise the real submit path with an intentionally forged UI grant.
    script = SCRIPT.replace(
        "render_typed_inputs(ui, working, working.nodes[0], 1)",
        "ui._granted = lambda *args: True\n    render_typed_inputs(ui, working, working.nodes[0], 1)",
    ).replace('action="test.typed"', 'action="core.map"')
    app = AppTest.from_string(script).run()
    app.radio[0].set_value("Editar JSON").run()
    app.text_area[0].set_value('{"items": [], "template": INVALID}').run()
    widget(app, "button", ":apply").click().run()
    assert app.error and not app.exception
    assert json.loads(app.json[-1].value)["Name"] == "old"

    viewer = AppTest.from_string(script.replace('roles=["ADMIN"]', 'roles=["VIEWER"]')).run()
    viewer.radio[0].set_value("Editar JSON").run()
    viewer.text_area[0].set_value('{"items": [], "template": {}}').run()
    widget(viewer, "button", ":apply").click().run()
    assert viewer.error and not viewer.exception
    assert json.loads(viewer.json[-1].value)["Name"] == "old"
    first = initial_config("core.filter")
    first["items"].append("changed")
    assert initial_config("core.filter")["items"] == []
    assert initial_config("core.start") == {}
