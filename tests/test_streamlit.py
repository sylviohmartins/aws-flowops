import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from flowops.domain.models import Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.streamlit.ui import NAVIGATION


class StreamlitSmokeTests(unittest.TestCase):
    @staticmethod
    def _element(elements: Any, label: str) -> Any:
        return next(element for element in elements if element.label == label)

    def test_standalone_workspace_pages_render_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("FLOWOPS_DATABASE")
            os.environ["FLOWOPS_DATABASE"] = str(Path(temp) / "ui.db")
            try:
                script = Path(__file__).resolve().parents[1] / "standalone_app.py"
                app = AppTest.from_file(script).run(timeout=20)
                self.assertEqual(list(app.exception), [])
                self.assertEqual(app.title[0].value, "AWS FlowOps Studio")
                self.assertGreaterEqual(len(app.metric), 5)

                for page in NAVIGATION:
                    app.sidebar.radio[0].set_value(page)
                    app.run(timeout=20)
                    self.assertEqual(list(app.exception), [], page)
            finally:
                if previous is None:
                    os.environ.pop("FLOWOPS_DATABASE", None)
                else:
                    os.environ["FLOWOPS_DATABASE"] = previous

    def test_standalone_create_publish_execute_and_history_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("FLOWOPS_DATABASE")
            database = Path(temp) / "e2e.db"
            os.environ["FLOWOPS_DATABASE"] = str(database)
            try:
                script = Path(__file__).resolve().parents[1] / "standalone_app.py"
                app = AppTest.from_file(script).run(timeout=20)
                self.assertEqual(list(app.exception), [])

                app.sidebar.radio[0].set_value("Runbooks")
                app.run(timeout=20)
                self._element(app.text_input, "Name override").set_value("Smoke Runbook")
                self._element(app.button, "Create runbook").click()
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])

                repository = Repository(database)
                books = repository.list_runbooks("Smoke Runbook")
                self.assertEqual(len(books), 1)
                book = books[0]
                self.assertEqual(book.name, "Smoke Runbook")
                self.assertEqual(repository.versions(book.id), [])

                app.sidebar.radio[0].set_value("Editor")
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])
                publish = self._element(app.button, "Publish version")
                self.assertFalse(publish.disabled)
                publish.click()
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])
                self.assertEqual(Repository(database).versions(book.id), [1])

                app.sidebar.radio[0].set_value("Execute")
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])
                self._element(app.button, "Submit execution").click()
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])

                store = ExecutionStore(Repository(database))
                deadline = time.monotonic() + 3
                executions = store.history()
                while (
                    executions
                    and executions[0].status
                    not in {
                        Status.SUCCESS,
                        Status.FAILED,
                        Status.CANCELLED,
                    }
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                    executions = store.history()
                self.assertEqual(len(executions), 1)
                self.assertEqual(executions[0].status, Status.SUCCESS)
                self.assertEqual(executions[0].snapshot.name, "Smoke Runbook")

                app.sidebar.radio[0].set_value("Executions")
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])
                self._element(app.selectbox, "Execution detail")

                app.sidebar.radio[0].set_value("Audit")
                app.run(timeout=20)
                self.assertEqual(list(app.exception), [])
                events = Repository(database).events(executions[0].id)
                self.assertTrue(any(event["event"] == "EXECUTION_REQUESTED" for event in events))
                self.assertTrue(any(event["event"] == "EXECUTION_COMPLETED" for event in events))
            finally:
                if previous is None:
                    os.environ.pop("FLOWOPS_DATABASE", None)
                else:
                    os.environ["FLOWOPS_DATABASE"] = previous


if __name__ == "__main__":
    unittest.main()
