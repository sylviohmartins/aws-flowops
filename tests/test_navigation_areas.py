from streamlit.testing.v1 import AppTest

from flowops.streamlit.navigation import AREAS, PAGE_LABELS, navigation_pages


def test_navigation_areas_keep_stable_ids_and_all_capabilities():
    assert navigation_pages("Todas as áreas") == list(PAGE_LABELS)
    assert navigation_pages("unknown") == list(PAGE_LABELS)
    assert set().union(
        *(set(pages) for area, pages in AREAS.items() if area != "Todas as áreas")
    ) == set(PAGE_LABELS)


def test_intent_filter_preserves_working_drafts_and_contextual_destination(tmp_path):
    app = AppTest.from_string(
        f"""
from flowops.streamlit import FlowOpsPage
from flowops.domain.models import Identity, AWSContext
from flowops.persistence.repository import Repository
FlowOpsPage(Identity(id="author",roles=["ADMIN"]), AWSContext(), repository=Repository({str(tmp_path / "areas.db")!r})).render()
""",
        default_timeout=30,
    ).run()
    app.session_state["flowops:working:test"] = {"body": "preserved"}
    area = "flowops:navigation-area"
    app.sidebar.selectbox(key=area).set_value("Operar").run()
    assert app.sidebar.radio(key="flowops:navigation").options == [
        PAGE_LABELS[p] for p in AREAS["Operar"]
    ]
    app.sidebar.radio(key="flowops:navigation").set_value("Approvals").run()
    assert not app.exception
    app.session_state["flowops:next-page"] = "Editor"
    app.run()
    assert app.sidebar.selectbox(key=area).value == "Todas as áreas"
    assert app.sidebar.radio(key="flowops:navigation").value == "Editor"
    assert app.session_state["flowops:working:test"]["body"] == "preserved"
