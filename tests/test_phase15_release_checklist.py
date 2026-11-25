import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestPhase15ReleaseChecklist(unittest.TestCase):
    def test_release_metadata_and_workflows_exist(self) -> None:
        self.assertTrue((ROOT / "CHANGELOG.md").exists())
        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertTrue((ROOT / "README.md").exists())
        self.assertTrue((ROOT / "README.fa.md").exists())
        self.assertTrue((ROOT / ".gitignore").exists())
        self.assertTrue((ROOT / ".github" / "workflows" / "ci.yml").exists())
        self.assertTrue((ROOT / ".github" / "workflows" / "workflow.yml").exists())
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.mypy]", pyproject)
        self.assertIn("[tool.ruff]", pyproject)
        self.assertIn("LGPL-3.0-or-later", pyproject)
        self.assertIn('version = "1.0.0"', pyproject)
