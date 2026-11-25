import ast
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from shirdal.cli import main as cli_main


class TestPhase11CLI(unittest.TestCase):
    def test_cli_new_scaffolds_valid_python_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli_main(["new", "my_bot", "--adapter", "mock", "--dir", tmp])
            self.assertEqual(rc, 0)

            proj = Path(tmp) / "my_bot"
            self.assertTrue((proj / "main.py").exists())
            self.assertTrue((proj / "plugins" / "ping.py").exists())
            self.assertTrue((proj / ".env.example").exists())

            ast.parse((proj / "main.py").read_text(encoding="utf-8"))
            ast.parse((proj / "plugins" / "ping.py").read_text(encoding="utf-8"))

    def test_cli_doctor_reports_environment(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["doctor"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Python:", out)
        self.assertIn("SQLite:", out)
        self.assertIn("telethon:", out)
