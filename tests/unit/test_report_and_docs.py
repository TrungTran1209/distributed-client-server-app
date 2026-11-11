import importlib.util
import inspect
from pathlib import Path
import unittest

from collab.server.server import CollaborationServer

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_REPORT_PATH = REPO_ROOT / "docs" / "report" / "build_report.py"


def _load_build_report():
    spec = importlib.util.spec_from_file_location("build_report", BUILD_REPORT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportAndDocsTests(unittest.TestCase):
    def test_markdown_to_html_renders_links_without_raw_brackets(self):
        build_report = _load_build_report()

        rel_html = build_report.markdown_to_html(
            "Sơ đồ chi tiết tại [`docs/state-diagrams.md`](../state-diagrams.md)."
        )
        self.assertIn("<code>docs/state-diagrams.md</code>", rel_html)
        self.assertNotIn("](../state-diagrams.md)", rel_html)
        self.assertNotIn("[<code>", rel_html)

        ext_html = build_report.markdown_to_html(
            "Tài liệu [Python SSL](https://docs.python.org/3/library/ssl.html)."
        )
        self.assertIn('<a href="https://docs.python.org/3/library/ssl.html">Python SSL</a>', ext_html)
        self.assertNotIn("](https://", ext_html)

    def test_docs_match_server_timeout_defaults_and_cli_commands(self):
        sig = inspect.signature(CollaborationServer.__init__)
        default_idle = sig.parameters["idle_timeout"].default
        default_auth = sig.parameters["auth_timeout"].default
        self.assertEqual(default_idle, 90)
        self.assertEqual(default_auth, 60)

        report_md = (REPO_ROOT / "docs" / "report" / "technical-report.md").read_text(encoding="utf-8")
        arch_md = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        state_md = (REPO_ROOT / "docs" / "state-diagrams.md").read_text(encoding="utf-8")

        self.assertIn("90 giây", report_md)
        self.assertNotIn("mặc định 300 giây", report_md)
        self.assertIn("`/logout`", report_md.split("## 9. CLI và vận hành", 1)[1])

        self.assertIn("idle_timeout = 90s", arch_md)
        self.assertNotIn("idle_timeout = 300s", arch_md)

        self.assertIn("90s", state_md)
        self.assertIn("60s", state_md)
        self.assertNotIn("timeout 10s", state_md)
        self.assertNotIn("300s", state_md)

        build_report = _load_build_report()
        rendered_report = build_report.markdown_to_html(report_md)
        self.assertNotIn("](../", rendered_report)


if __name__ == "__main__":
    unittest.main()
