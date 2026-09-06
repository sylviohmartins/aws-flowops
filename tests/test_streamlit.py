import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from flowops.streamlit.ui import NAVIGATION


class StreamlitSmokeTests(unittest.TestCase):
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
