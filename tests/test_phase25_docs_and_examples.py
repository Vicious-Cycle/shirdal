import ast
import unittest
from pathlib import Path

import shirdal

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPhase25DocsAndExamples(unittest.TestCase):
    def test_docs_pages_and_repo_files_exist(self) -> None:
        required_files = [
            "README.md",
            "README.fa.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "mkdocs.yml",
            "docs/getting-started.md",
            "docs/bot-api.md",
            "docs/rich-messages.md",
            "docs/webhook-and-deployment.md",
            "docs/native-mtproto.md",
            "docs/fa/README.md",
            "SECURITY.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/feature_request.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
        ]
        for rel in required_files:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), f"Missing documentation file: {rel}")
            self.assertGreater(len(path.read_text(encoding="utf-8").strip()), 50)

    def test_all_examples_parse_cleanly(self) -> None:
        examples_dir = REPO_ROOT / "examples"
        py_files = list(examples_dir.rglob("*.py"))
        self.assertGreaterEqual(len(py_files), 2)
        for py_file in py_files:
            ast.parse(py_file.read_text(encoding="utf-8"))

    def test_documented_public_symbols_are_exported(self) -> None:
        documented_symbols = [
            "Shirdal",
            "SelfBot",
            "BotAPIAdapter",
            "NativeMTProtoAdapter",
            "WebhookServer",
            "ButtonStyle",
            "button",
            "inline_keyboard",
            "reply_button",
            "reply_keyboard",
            "custom_emoji",
            "custom_emoji_entity",
            "date_time",
            "date_time_entity",
            "DraftStream",
            "RichDraftStream",
            "rich_message",
            "rich_heading",
            "rich_paragraph",
            "rich_table",
            "rich_details",
            "rich_blockquote",
            "rich_code",
            "rich_math",
            "rich_buttons",
            "rich_divider",
            "rich_footer",
            "rich_thinking",
        ]
        for sym in documented_symbols:
            self.assertTrue(hasattr(shirdal, sym), f"Missing public export: {sym}")
