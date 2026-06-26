"""Regression tests for Amazon Order Status 2.0 model helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


def _load_models_module():
    integration_dir = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "amazon_order_status"
    )
    package = types.ModuleType("amazon_order_status")
    package.__path__ = [str(integration_dir)]
    sys.modules["amazon_order_status"] = package

    spec = importlib.util.spec_from_file_location(
        "amazon_order_status.models",
        integration_dir / "models.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["amazon_order_status.models"] = module
    spec.loader.exec_module(module)
    return module


models = _load_models_module()


class ModelsTest(unittest.TestCase):
    def test_shipment_id_normalizes_item_key(self):
        self.assertEqual(
            "123-4567890-1234567:my-cool-item",
            models.shipment_id_for(
                "123-4567890-1234567",
                "  My Cool_Item!!  ",
                None,
            ),
        )

    def test_shipment_id_uses_default_without_item_key(self):
        self.assertEqual(
            "123-4567890-1234567:default",
            models.shipment_id_for(
                "123-4567890-1234567",
                None,
                "https://www.amazon.de/gp/your-account/ship-track/TRACKING12345",
            ),
        )

    def test_order_rollup_reports_partial_delivery(self):
        shipments = [
            {"status": "Delivered", "ignored": False},
            {"status": "Out for delivery", "ignored": False},
        ]

        self.assertEqual(
            "Partially delivered",
            models.rollup_order_status(shipments),
        )

    def test_order_rollup_prioritizes_problem_statuses(self):
        shipments = [
            {"status": "Delivered", "ignored": False},
            {"status": "Delayed", "ignored": False},
        ]

        self.assertEqual("Delayed", models.rollup_order_status(shipments))

    def test_ignored_order_rolls_up_to_ignored(self):
        self.assertEqual(
            "Ignored",
            models.rollup_order_status(
                [{"status": "Delivered", "ignored": True}],
                ignored=True,
            ),
        )

    def test_build_order_and_upsert_shipment_keep_nested_contract(self):
        shipment = models.build_shipment(
            "123-4567890-1234567",
            "Shipped",
            "2026-06-26T10:00:00+00:00",
            "Versendet: Example",
            "example",
            "Example",
            "https://www.amazon.de/gp/your-account/ship-track/example",
            {"delivery_estimate": "morgen", "item_count": 1},
        )
        order = models.build_order(
            "123-4567890-1234567",
            shipment,
            "Versendet: Example",
            "2026-06-26T10:00:00+00:00",
        )

        self.assertEqual("123-4567890-1234567", order["order_id"])
        self.assertEqual("Shipped", order["status"])
        self.assertEqual(1, len(order["shipments"]))
        self.assertEqual(shipment["shipment_id"], order["shipments"][0]["shipment_id"])
        self.assertEqual(1, order["item_count"])

    def test_manual_status_on_one_shipment_updates_rollup(self):
        first = models.build_shipment(
            "123-4567890-1234567",
            "Shipped",
            "2026-06-26T10:00:00+00:00",
            "Versendet: First",
            "first",
            "First",
            None,
            {},
        )
        second = models.build_shipment(
            "123-4567890-1234567",
            "Delivered",
            "2026-06-26T11:00:00+00:00",
            "Zugestellt: Second",
            "second",
            "Second",
            None,
            {},
        )
        order = models.build_order(
            "123-4567890-1234567",
            first,
            "Versendet: First",
            "2026-06-26T10:00:00+00:00",
        )
        order = models.upsert_shipment(order, second)

        changed = models.set_manual_status(
            order,
            "Delivered",
            "2026-06-26T12:00:00+00:00",
            shipment_id=first["shipment_id"],
            delivered_at="manual",
        )

        self.assertTrue(changed)
        self.assertEqual("Delivered", order["status"])
        self.assertTrue(order["shipments"][0]["manual"])
        self.assertEqual("manual", order["shipments"][0]["delivered_at"])


if __name__ == "__main__":
    unittest.main()
