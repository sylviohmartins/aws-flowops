from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from flowops.persistence.repository import Repository


def element(elements: Any, label: str) -> Any:
    return next(item for item in elements if item.label == label)


def script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "standalone_app.py"


def test_editor_metadata_parameters_insert_remove_validate_and_save_journey() -> None:
    with tempfile.TemporaryDirectory() as temp:
        previous = os.environ.get("FLOWOPS_DATABASE")
        database = Path(temp) / "editor.db"
        os.environ["FLOWOPS_DATABASE"] = str(database)
        try:
            app = AppTest.from_file(script_path()).run(timeout=20)
            app.sidebar.radio[0].set_value("Runbooks")
            app.run(timeout=20)
            element(app.text_input, "Name override").set_value("Editor Journey")
            element(app.button, "Create runbook").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            repository = Repository(database)
            book = repository.list_runbooks("Editor Journey")[0]

            app.sidebar.radio[0].set_value("Editor")
            app.run(timeout=20)
            assert list(app.exception) == []

            element(app.text_input, "Name").set_value("Editor Journey Updated")
            element(app.text_area, "Description").set_value("edited through Streamlit")
            element(app.text_input, "Tags (comma separated)").set_value("coverage, editor")
            element(app.button, "Apply metadata").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            parameter_schema = (
                '{"batch":{"type":"integer","required":true,'
                '"default":2,"description":"Batch size"}}'
            )
            element(app.text_area, "Parameter schema JSON").set_value(parameter_schema)
            element(app.button, "Apply parameters").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            element(app.button, "Save draft").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            saved, revision = Repository(database).get_draft(book.id)
            assert revision == 2
            assert saved.name == "Editor Journey Updated"
            assert saved.description == "edited through Streamlit"
            assert saved.tags == ["coverage", "editor"]
            assert saved.parameters["batch"].default == 2

            element(app.selectbox, "Action").set_value("core.approval")
            element(app.button, "Insert before End").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            element(app.button, "Save draft").click()
            app.run(timeout=20)
            assert list(app.exception) == []

            with_node, revision = Repository(database).get_draft(book.id)
            inserted = next(node for node in with_node.nodes if node.action == "core.approval")
            assert revision == 3

            element(app.selectbox, "Node properties").set_value(inserted.id)
            app.run(timeout=20)
            element(app.text_input, "Label").set_value("Approval checkpoint")
            element(app.selectbox, "Failure policy").set_value("CONTINUE")
            element(app.button, "Apply node properties").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            element(app.button, "Save draft").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            changed, revision = Repository(database).get_draft(book.id)
            changed_node = next(node for node in changed.nodes if node.id == inserted.id)
            assert revision == 4
            assert changed_node.label == "Approval checkpoint"
            assert changed_node.failure_policy == "CONTINUE"

            element(app.button, "Validate").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            assert any("Valid workflow" in success.value for success in app.success)

            element(app.selectbox, "Node properties").set_value(inserted.id)
            app.run(timeout=20)
            element(app.button, "Remove selected node").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            element(app.button, "Save draft").click()
            app.run(timeout=20)
            assert list(app.exception) == []
            final, revision = Repository(database).get_draft(book.id)
            assert revision == 5
            assert all(node.id != inserted.id for node in final.nodes)
        finally:
            if previous is None:
                os.environ.pop("FLOWOPS_DATABASE", None)
            else:
                os.environ["FLOWOPS_DATABASE"] = previous
