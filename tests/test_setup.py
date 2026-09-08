from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

from scripts import setup


class SetupTests(unittest.TestCase):
    def test_virtual_environment_is_real_and_reuse_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "environment with spaces"
            python = setup.prepare_environment(target, install=True)
            marker = target / "preserved.txt"
            marker.write_text("keep")
            self.assertEqual(setup.prepare_environment(target, install=False), python)
            self.assertEqual(marker.read_text(), "keep")
            result = subprocess.check_output(
                [str(python), "-c", "import sys; print(sys.prefix != sys.base_prefix)"], text=True
            )
            self.assertEqual(result.strip(), "True")

    def test_occupied_directory_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.txt"
            marker.write_text("user data")
            with self.assertRaisesRegex(ValueError, "ocupado"):
                setup.prepare_environment(Path(directory), install=True)
            self.assertEqual(marker.read_text(), "user data")
            self.assertEqual(list(Path(directory).iterdir()), [marker])

    def test_run_only_does_not_create_an_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing"
            self.assertEqual(setup.main(["--venv", str(target), "--run-only"]), 1)
            self.assertFalse(target.exists())

    def test_failed_install_never_starts_application(self) -> None:
        with (
            patch.object(setup, "prepare_environment", return_value=Path(sys.executable)),
            patch.object(
                setup.subprocess, "run", side_effect=subprocess.CalledProcessError(17, ["pip"])
            ) as run,
        ):
            self.assertEqual(setup.main([]), 17)
            run.assert_called_once()
            self.assertIn("install", run.call_args.args[0])

    def test_install_only_includes_requested_extras_without_starting(self) -> None:
        with (
            patch.object(setup, "prepare_environment", return_value=Path(sys.executable)),
            patch.object(setup.subprocess, "run") as run,
            patch.dict(os.environ, {"FLOWOPS_DATABASE_URL": "postgresql://example.invalid/db"}),
        ):
            self.assertEqual(setup.main(["--install-only", "--dev"]), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(str(setup.ROOT) + "[dev,postgres]", commands[0])
            self.assertFalse(any("run" in command for command in commands))

    def test_invalid_options_fail_before_installing(self) -> None:
        with patch.object(setup, "prepare_environment") as prepare:
            for args in (["--port", "65536"], ["--run-only", "--dev"], ["--app", "absent.py"]):
                with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                    setup.main(args)
                self.assertEqual(error.exception.code, 2)
            with (
                patch.object(setup.sys, "version_info", (3, 11)),
                self.assertRaises(SystemExit) as error,
            ):
                setup.main([])
            self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()

    def test_local_mode_provisions_before_seed_and_uses_postgres_extra(self) -> None:
        with (
            patch.object(setup, "prepare_environment", return_value=Path(sys.executable)),
            patch.object(setup.subprocess, "run") as run,
            patch.dict(os.environ, {"FLOWOPS_DATABASE_URL": "postgresql://do-not-use.invalid/db"}),
        ):
            self.assertEqual(setup.main(["--local", "--install-only"]), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], ["docker", "info"])
            self.assertTrue(any("--wait" in command for command in commands))
            self.assertTrue(any(str(setup.ROOT) + "[postgres]" in command for command in commands))
            self.assertEqual(commands[-1][-2:], ["-m", "flowops.providers.aws.lab"])
            self.assertFalse(any("streamlit" in command for command in commands))
            self.assertTrue(all("do-not-use" not in str(command) for command in commands))

    def test_local_run_only_still_seeds_and_docker_failure_stops_setup(self) -> None:
        with (
            patch.object(setup, "prepare_environment", return_value=Path(sys.executable)),
            patch.object(setup.subprocess, "run") as run,
        ):
            self.assertEqual(setup.main(["--local", "--run-only", "--no-browser"]), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertFalse(any("install" in command for command in commands))
            self.assertIn(str(setup.ROOT / "local_app.py"), commands[-1])
        with (
            patch.object(setup, "prepare_environment") as prepare,
            patch.object(setup.subprocess, "run", side_effect=FileNotFoundError("Docker ausente")),
        ):
            self.assertEqual(setup.main(["--local"]), 1)
            prepare.assert_not_called()

    def test_stop_only_preserves_volumes_and_local_app_is_fixed(self) -> None:
        with (
            patch.object(setup, "prepare_environment") as prepare,
            patch.object(setup.subprocess, "run") as run,
        ):
            self.assertEqual(setup.main(["--stop-local"]), 0)
            self.assertEqual(run.call_args.args[0][-1], "stop")
            prepare.assert_not_called()
            with self.assertRaises(SystemExit):
                setup.main(["--local", "--app", "standalone_app.py"])


@unittest.skipUnless(os.getenv("FLOWOPS_TEST_SETUP") == "1", "Setup installation smoke is opt-in")
class SetupSmokeTests(unittest.TestCase):
    def test_install_reuse_and_launch_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            target = work / "virtual environment"
            env = os.environ | {"FLOWOPS_DATABASE": str(work / "demo.db")}
            env.pop("FLOWOPS_DATABASE_URL", None)
            if os.name == "nt":
                # CALL keeps cmd /c from stripping the leading quoted batch-file path.
                launcher = ["cmd", "/d", "/c", "call", str(setup.ROOT / "setup.cmd")]
            else:
                launcher = ["bash", str(setup.ROOT / "setup.sh")]
            command = [*launcher, "--venv", str(target)]
            for _ in range(2):
                subprocess.run(
                    [*command, "--install-only"], cwd=work, env=env, check=True, timeout=300
                )
            python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            # Render the real bootstrap as well as checking the launched HTTP server.
            subprocess.run(
                [
                    str(python),
                    "-c",
                    "from streamlit.testing.v1 import AppTest; "
                    f"app = AppTest.from_file({str(setup.ROOT / 'standalone_app.py')!r}).run(timeout=60); "
                    "assert not app.exception, app.exception",
                ],
                cwd=work,
                env=env,
                check=True,
                timeout=90,
            )
            self.assertTrue((work / "demo.db").is_file())
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            with (work / "server.log").open("w+") as log:
                process = subprocess.Popen(
                    [*command, "--run-only", "--no-browser", "--port", str(port)],
                    cwd=work,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                )
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            with urlopen(
                                f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                            ) as response:
                                self.assertEqual(response.status, 200)
                                self.assertEqual(response.read(), b"ok")
                                print("Setup smoke PASS: install, reuse, AppTest and HTTP startup")
                                return
                        except (URLError, TimeoutError):
                            time.sleep(0.2)
                    log.seek(0)
                    self.fail(f"Setup did not start Streamlit: {log.read()}")
                finally:
                    if process.poll() is None:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                check=True,
                                stdout=subprocess.DEVNULL,
                            )
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)


if __name__ == "__main__":
    unittest.main()
