"""Check Python startup without downloading packages or opening the UI."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


source = Path(__file__).resolve().parents[1] / "QR.PY"
spec = importlib.util.spec_from_loader("qr_launcher", importlib.machinery.SourceFileLoader("qr_launcher", str(source)))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temp = source.parent / ".cache" / "tmp"
        temp.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=temp)
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.python = self.directory / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.enterContext(patch.object(launcher, "__file__", str(self.directory / "QR.PY")))
        self.enterContext(patch.dict(os.environ))
        self.find_spec = self.enterContext(patch.object(launcher.importlib.util, "find_spec", return_value=None))
        self.run = self.enterContext(patch.object(launcher.subprocess, "run", return_value=Mock(returncode=0)))
        self.call = self.enterContext(patch.object(launcher.subprocess, "call", return_value=0))
        self.builder = self.enterContext(patch("venv.EnvBuilder"))
        self.enterContext(patch.object(launcher, "print"))

    def existing_environment(self):
        self.python.parent.mkdir(parents=True)
        self.python.touch()

    def test_installed_dependencies_need_no_setup(self):
        self.find_spec.return_value = object()
        self.assertIsNone(launcher._prepare_dependencies())
        self.builder.assert_not_called()
        self.run.assert_not_called()
        self.call.assert_not_called()

    def test_first_start_creates_environment_and_installs_dependencies(self):
        self.run.side_effect = [Mock(returncode=1), Mock(returncode=1), Mock(returncode=0), Mock(returncode=0), Mock(returncode=0)]
        with patch.object(sys, "argv", [str(source), "example.com", "-o", "my qr.svg"]):
            self.assertEqual(launcher._prepare_dependencies(), 0)
        self.builder.assert_called_once_with(with_pip=True)
        self.builder.return_value.create.assert_called_once_with(self.directory / ".venv")
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertIn([str(self.python), "-m", "ensurepip", "--upgrade"], commands)
        self.assertIn([str(self.python), "-m", "pip", "install", "-r", str(self.directory / "requirements.txt")], commands)
        self.call.assert_called_once_with([str(self.python), str(self.directory / "QR.PY"), "example.com", "-o", "my qr.svg"])
        self.assertEqual(os.environ["TEMP"], str(self.directory / ".cache" / "tmp"))

    def test_existing_environment_launches_without_installing_again(self):
        self.existing_environment()
        self.call.return_value = 7
        with patch.object(sys, "argv", [str(source)]):
            self.assertEqual(launcher._prepare_dependencies(), 7)
        self.builder.assert_not_called()
        self.run.assert_called_once_with([str(self.python), "-c", "import " + ", ".join(launcher.DEPENDENCIES)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_current_environment_continues_without_relaunching(self):
        self.existing_environment()
        with patch.object(sys, "prefix", str(self.directory / ".venv")):
            self.assertIsNone(launcher._prepare_dependencies())
        self.call.assert_not_called()

    def test_setup_failure_returns_error_without_opening_app(self):
        error = subprocess.CalledProcessError(1, [str(self.python), "-m", "pip"])
        with patch.object(sys, "argv", [str(source)]), patch.object(launcher, "_prepare_dependencies", side_effect=error), patch.object(launcher, "_report_error") as report:
            self.assertEqual(launcher.main(), 1)
        self.assertIn("setup failed", report.call_args.args[0])
        self.assertTrue(report.call_args.args[1])
        self.call.assert_not_called()

    def test_safe_rendering_flag_is_forwarded_to_the_desktop(self):
        launch = Mock()
        with patch.object(sys, "argv", [str(source), "--safe-rendering"]), patch.object(launcher, "_prepare_dependencies", return_value=None), patch.dict(sys.modules, {"qr_maker.app": SimpleNamespace(main=launch)}):
            self.assertEqual(launcher.main(), 0)
        launch.assert_called_once_with(safe_rendering=True)


if __name__ == "__main__":
    unittest.main()
