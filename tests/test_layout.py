"""Layout structure stays presentation-only and accessible to Streamlit hosts."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.streamlit.navigation import PAGE_LABELS
from flowops.templates import dynamodb_query_lambda


def test_all_pages_share_scoped_layout_without_persisting_on_render(tmp_path: Path) -> None:
    database = tmp_path / "layout.db"
    repo = Repository(database)
    book = dynamodb_query_lambda("demo-author", "default")
    revision = repo.save_draft(book, "demo-author")
    published = repo.publish(book.id, "demo-author", revision)
    saved_draft = repo.get_draft(book.id)
    events = repo.events()
    app = AppTest.from_string(
        f"""
import streamlit as st
from flowops.streamlit import FlowOpsPage
from flowops.domain.models import Identity, AWSContext
from flowops.persistence.repository import Repository
st.header('Conteúdo da aplicação hospedeira')
FlowOpsPage(Identity(id='demo-author', roles=['ADMIN']), AWSContext(),
            repository=Repository({str(database)!r})).render()
""",
        default_timeout=30,
    ).run()
    for page in PAGE_LABELS:
        app.sidebar.radio(key="flowops:navigation").set_value(page).run()
        assert not app.exception, (page, app.exception)
        assert app.header[0].value == "Conteúdo da aplicação hospedeira"
        styles = [element.value for element in app.get("html")]
        assert any(".st-key-flowops-workspace" in css for css in styles)
        if page == "Executions":
            # Seven controls in a single grid, rather than unrelated 4/3 tracks.
            rows = [
                row
                for row in app.get("flex_container")
                if len(row.children) == 7
                and all(child.type == "column" for child in row.children.values())
            ]
            assert len(rows) == 1
        assert repo.get_draft(book.id) == saved_draft
        assert repo.version(book.id, 1) == published
        assert repo.events() == events
        assert ExecutionStore(repo).history() == []


def test_styles_are_packaged_and_contain_no_external_resources() -> None:
    import flowops.streamlit.layout as layout

    css = Path(layout.__file__).with_name("workspace.css").read_text(encoding="utf-8")
    assert "grid-template-columns" in css
    assert "minmax(min(100%, 12rem), 1fr)" in css
    assert ".st-key-flowops-node-editor" in css
    assert ".st-key-flowops-navigation" in css
    assert "st-emotion-cache" not in css
    assert "@import" not in css and "url(" not in css
    assert "overflow: hidden" not in css  # Never conceal page overflow to pass a check.
