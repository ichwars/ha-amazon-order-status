"""Release documentation regression tests for the 2.0 release."""

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

STATUS_ENTITY_IDS = (
    "sensor.amazon_orders_ordered",
    "sensor.amazon_orders_shipped",
    "sensor.amazon_orders_out_for_delivery",
    "sensor.amazon_orders_delivery_attempted",
    "sensor.amazon_orders_pickup_ready",
    "sensor.amazon_orders_delayed",
    "sensor.amazon_orders_delivery_problem",
    "sensor.amazon_orders_undeliverable",
    "sensor.amazon_orders_partially_delivered",
    "sensor.amazon_orders_delivered",
    "sensor.amazon_orders_canceled",
    "sensor.amazon_orders_return_started",
    "sensor.amazon_orders_refunded",
    "sensor.amazon_orders_ignored",
)

STATUS_VALUES = (
    "Ordered",
    "Shipped",
    "Out for delivery",
    "Delivery attempted",
    "Pickup ready",
    "Delayed",
    "Delivery problem",
    "Undeliverable",
    "Partially delivered",
    "Delivered",
    "Canceled",
    "Return started",
    "Refunded",
    "Ignored",
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
    """Verify release metadata and upgrade documentation for 2.0.x."""

    def test_manifest_version_is_2_0_2(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual("2.0.2", manifest["version"])

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

    def test_readme_lists_all_status_sensor_entity_ids(self):
        text = _readme_text()

        for entity_id in STATUS_ENTITY_IDS:
            with self.subTest(entity_id=entity_id):
                self.assertIn(entity_id, text)

    def test_dashboard_example_covers_all_2_0_statuses(self):
        dashboard = _dashboard_section(_readme_text())
        self.assertTrue(dashboard, "README is missing a ## Dashboard section")

        for status in STATUS_VALUES:
            with self.subTest(status=status):
                self.assertIn(status, dashboard)


if __name__ == "__main__":
    unittest.main()
