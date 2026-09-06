import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class StreamlitSmokeTests(unittest.TestCase):
    def test_standalone_dashboard_starts_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("FLOWOPS_DATABASE")
            os.environ["FLOWOPS_DATABASE"] = str(Path(temp) / "ui.db")
            try:
                script = Path(__file__).resolve().parents[1] / "standalone_app.py"
                app = AppTest.from_file(script).run(timeout=20)
                self.assertEqual(list(app.exception), [])
                self.assertEqual(app.title[0].value, "AWS FlowOps Studio")
                self.assertGreaterEqual(len(app.metric), 5)
            finally:
                if previous is None:
                    os.environ.pop("FLOWOPS_DATABASE", None)
                else:
                    os.environ["FLOWOPS_DATABASE"] = previous
