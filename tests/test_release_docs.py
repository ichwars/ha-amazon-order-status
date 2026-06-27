"""Release documentation regression tests for the 2.0.0 release."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "custom_components" / "amazon_order_status" / "manifest.json"
README_PATH = ROOT / "README.md"

REQUIRED_README_SNIPPETS = (
    "clear_existing: true",
    "shipments",
    "sensor.amazon_orders_partially_delivered",
    "amazon_order_status.set_status",
    "amazon_order_status.mark_delivered",
    "amazon_order_status.ignore_order",
    "amazon_order_status.restore_order",
)

UNSAFE_DASHBOARD_PATTERNS = (
    "o.delivery_window",
    "o.tracking_url",
    "s.delivery_window",
    "s.tracking_url",
)


def _readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _dashboard_section(text: str) -> str:
    start = text.find("## Dashboard")
    end = text.find("\n## ", start + 1) if start != -1 else -1
    if start == -1:
        return ""
    if end == -1:
        return text[start:]
    return text[start:end]


class ReleaseDocsTest(unittest.TestCase):
    """Verify release metadata and upgrade documentation for 2.0.0."""

    def test_manifest_version_is_2_0_0(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual("2.0.0", manifest["version"])

    def test_readme_contains_required_2_0_snippets(self):
        text = _readme_text()

        for snippet in REQUIRED_README_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_dashboard_example_avoids_unsafe_dot_access(self):
        dashboard = _dashboard_section(_readme_text())
        self.assertTrue(dashboard, "README is missing a ## Dashboard section")

        for pattern in UNSAFE_DASHBOARD_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, dashboard)


if __name__ == "__main__":
    unittest.main()
