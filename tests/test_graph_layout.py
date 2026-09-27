from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from flowops.domain.errors import AuthorizationError, WorkflowValidationError
from flowops.domain.models import Edge, Identity, Node, Runbook
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.streamlit.graph_layout import organize_workflow
from flowops.streamlit.ui import FlowOpsUI
from flowops.templates import dynamodb_query_lambda


def positions(book: Runbook) -> dict[str, tuple[float, float]]:
    return {node.id: node.position for node in book.nodes}


def without_positions(book: Runbook) -> dict:
    return book.model_dump(exclude={"nodes": {"__all__": {"position"}}})


def test_organization_preserves_definition_and_orders_branches_and_joins() -> None:
    book = dynamodb_query_lambda("author", "default")
    # Declaration order intentionally differs from dependencies and visual branch order.
    book.nodes.extend(
        [
            Node(id="recovery", action="core.set", config={"value": "review"}),
            Node(id="detached", action="dynamodb.query"),  # Incomplete, disconnected draft.
        ]
    )
    book.edges.extend(
        [
            Edge(source="query", target="recovery", branch="failure"),
            Edge(source="recovery", target="end"),
        ]
    )
    original = book.model_dump_json()
    arranged, undo = organize_workflow(book, 3)
    assert book.model_dump_json() == original
    assert without_positions(arranged) == without_positions(book)
    assert len(set(positions(arranged).values())) == len(book.nodes)
    for edge in book.edges:
        assert positions(arranged)[edge.source][0] < positions(arranged)[edge.target][0]
    assert undo is not None and undo.restore(arranged, 3) == book
    assert organize_workflow(arranged, 3) == (arranged, None)
    assert organize_workflow(book, 3)[0] == arranged


@pytest.mark.parametrize("size,chain", [(0, False), (1, False), (200, False), (200, True)])
def test_empty_single_and_maximum_graphs_stay_bounded(size: int, chain: bool) -> None:
    book = Runbook(name="Layout", nodes=[Node(id=f"n{i}", action="core.set") for i in range(size)])
    if chain:
        book.edges = [Edge(source=f"n{i}", target=f"n{i + 1}") for i in range(size - 1)]
    result, _ = organize_workflow(book, 1)
    assert len(result.nodes) == size
    assert len(set(positions(result).values())) == size
    assert all(0 <= coordinate <= 100000 for node in result.nodes for coordinate in node.position)


@pytest.mark.parametrize("invalid", ["duplicate", "unknown", "cycle", "self", "nodes", "edges"])
def test_invalid_structure_is_rejected_without_modification(invalid: str) -> None:
    book = Runbook(
        name="Invalid", nodes=[Node(id="a", action="core.set"), Node(id="b", action="core.set")]
    )
    if invalid == "duplicate":
        book.nodes.append(book.nodes[0].model_copy(deep=True))
    elif invalid == "unknown":
        book.edges = [Edge(source="a", target="missing")]
    elif invalid == "cycle":
        book.edges = [Edge(source="a", target="b"), Edge(source="b", target="a")]
    elif invalid == "self":
        book.edges = [Edge(source="a", target="a")]
    elif invalid == "nodes":
        book.nodes = [Node(id=f"n{i}", action="core.set") for i in range(201)]
    else:
        book.edges = [Edge(source="a", target="b") for _ in range(1001)]
    original = book.model_dump_json()
    with pytest.raises(WorkflowValidationError):
        organize_workflow(book, 1)
    assert book.model_dump_json() == original


def test_undo_preserves_new_configuration_but_rejects_stale_layout_and_revision() -> None:
    original = dynamodb_query_lambda("author", "default")
    arranged, undo = organize_workflow(original, 4)
    assert undo is not None
    arranged.nodes[1].label = "Novo nome"
    arranged.nodes[1].config["Limit"] = 12
    restored = undo.restore(arranged, 4)
    assert positions(restored) == positions(original)
    assert without_positions(restored) == without_positions(arranged)
    assert not undo.matches(arranged, 5)
    variants = [arranged.model_copy(deep=True) for _ in range(5)]
    variants[0].nodes[0].position = (1, 2)
    variants[1].edges[0].branch = "failure"
    variants[2].nodes.pop()
    variants[3].id = "another-book"
    variants[4].nodes.append(Node(id="fresh", action="core.set"))
    for candidate, revision in [(candidate, 4) for candidate in variants] + [(arranged, 5)]:
        before = candidate.model_dump_json()
        with pytest.raises(WorkflowValidationError, match="Não é possível desfazer"):
            undo.restore(candidate, revision)
        assert candidate.model_dump_json() == before


@pytest.mark.parametrize("clicked", ["Organizar fluxo", "Desfazer organização"])
def test_toolbar_rechecks_permission_even_if_a_disabled_button_is_submitted(clicked: str) -> None:
    book, undo = organize_workflow(dynamodb_query_lambda("author", "default"), 1)
    session = {f"flowops:layout-undo:{book.id}": undo}
    column = SimpleNamespace(button=lambda label, **kwargs: label == clicked)
    fake = SimpleNamespace(session_state=session, columns=lambda _: [column, column])
    ui = object.__new__(FlowOpsUI)
    ui.user = Identity(id="viewer", roles=["VIEWER"])
    ui._store_working = Mock()
    with patch.dict("sys.modules", {"streamlit": fake}), pytest.raises(AuthorizationError):
        ui._layout_tools(book, 1, editable=False)
    ui._store_working.assert_not_called()


@pytest.mark.parametrize("role", ["ADMIN", "VIEWER"])
def test_editor_organization_undo_and_explicit_save_journey(tmp_path: Path, role: str) -> None:
    database = tmp_path / "organize.db"
    repo = Repository(database)
    book = dynamodb_query_lambda("author", "default")
    revision = repo.save_draft(book, "author")
    published = repo.publish(book.id, "author", revision)
    before, revision = repo.get_draft(book.id)
    events = repo.events()
    app = AppTest.from_string(
        f"""
from flowops.streamlit import FlowOpsPage
from flowops.domain.models import Identity, AWSContext
from flowops.persistence.repository import Repository
FlowOpsPage(Identity(id='author', roles=[{role!r}]), AWSContext(),
            repository=Repository({str(database)!r})).render()
""",
        default_timeout=30,
    ).run()
    app.sidebar.radio(key="flowops:navigation").set_value("Editor").run()
    assert not app.exception

    def button(label: str):
        return next(item for item in app.button if item.label == label)

    def working() -> Runbook:
        return Runbook.model_validate_json(app.session_state[f"flowops:working:{book.id}"]["body"])

    assert button("Desfazer organização").disabled
    assert button("Organizar fluxo").disabled == (role == "VIEWER")
    if role == "ADMIN":
        button("Organizar fluxo").click().run()
        assert positions(working()) != positions(before)
        assert without_positions(working()) == without_positions(before)
        assert not button("Desfazer organização").disabled
        button("Organizar fluxo").click().run()
        assert any("já está organizado" in info.value for info in app.info)
        app.run()
        assert any("já está organizado" in info.value for info in app.info)
        assert not button("Desfazer organização").disabled
        app.selectbox(key=f"flowops:node:{book.id}").set_value("query").run()
        next(item for item in app.text_input if item.label == "Nome da etapa").set_value(
            "Consulta revisada"
        )
        button("Aplicar propriedades da etapa").click().run()
        edited = working()
        app.selectbox(key=f"flowops:node:{book.id}").set_value("query").run()
        button("Desfazer organização").click().run()
        assert positions(working()) == positions(before)
        assert without_positions(working()) == without_positions(edited)
        assert app.selectbox(key=f"flowops:node:{book.id}").value == "query"
        assert button("Desfazer organização").disabled
        assert not any("já está organizado" in info.value for info in app.info)
    app.run()
    assert not app.exception
    assert repo.get_draft(book.id) == (before, revision)
    assert repo.events() == events
    if role == "ADMIN":
        button("Organizar fluxo").click().run()
        expected = working()
        button("Salvar rascunho").click().run()
        saved, saved_revision = repo.get_draft(book.id)
        assert saved_revision == revision + 1
        assert positions(saved) == positions(expected)
        assert saved.nodes[1].label == "Consulta revisada"
        assert button("Desfazer organização").disabled
    assert not app.exception
    assert repo.version(book.id, published.version) == published
    assert ExecutionStore(repo).history() == []
