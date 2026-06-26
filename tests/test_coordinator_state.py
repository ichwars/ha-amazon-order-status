"""Regression tests for Amazon Order Status 2.0 coordinator state handling."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import types
import unittest


def _load_coordinator_module():
    bs4 = types.ModuleType("bs4")
    bs4.BeautifulSoup = object
    sys.modules["bs4"] = bs4
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda func: func
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.DataUpdateCoordinator = object
    update_coordinator.UpdateFailed = Exception
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = object
    sys.modules.update(
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.core": core,
            "homeassistant.config_entries": config_entries,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.helpers.storage": storage,
        }
    )
    integration_dir = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "amazon_order_status"
    )
    package = types.ModuleType("amazon_order_status")
    package.__path__ = [str(integration_dir)]
    sys.modules["amazon_order_status"] = package
    for name in ("const", "models", "parser", "coordinator"):
        spec = importlib.util.spec_from_file_location(
            f"amazon_order_status.{name}",
            integration_dir / f"{name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"amazon_order_status.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["amazon_order_status.coordinator"]


coordinator = _load_coordinator_module()


class CoordinatorStateTest(unittest.IsolatedAsyncioTestCase):
    def _fake(self):
        fake = coordinator.AmazonOrdersCoordinator.__new__(
            coordinator.AmazonOrdersCoordinator
        )
        fake._orders = {}
        fake.expose_parser_debug = False
        fake.last_check = None
        fake.last_scan_stats = {}
        fake.entry = SimpleNamespace(entry_id="entry-1")
        fake.async_set_updated_data = lambda data: setattr(fake, "data", data)

        async def save_state(processed_until=None):
            fake.saved = processed_until or True

        fake.async_save_state = save_state
        return fake

    def test_upsert_creates_shipments_and_partial_rollup(self):
        fake = self._fake()

        fake._upsert_order_event(
            "123-4567890-1234567",
            "Delivered",
            "Zugestellt: First",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "First"},
        )
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Out for delivery",
            "In Zustellung: Second",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Second"},
        )

        order = fake._orders["123-4567890-1234567"]
        self.assertEqual("Partially delivered", order["status"])
        self.assertEqual(2, len(order["shipments"]))

    def test_upsert_keeps_top_level_item_count_aggregated_across_shipments(self):
        fake = self._fake()

        fake._upsert_order_event(
            "123-4567890-1234567",
            "Delivered",
            "Zugestellt: First",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "First", "item_count": 2},
        )
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Out for delivery",
            "In Zustellung: Second",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Second", "item_count": 3},
        )

        order = fake._orders["123-4567890-1234567"]
        self.assertEqual(5, order["item_count"])
        self.assertEqual(5, fake._current_data()[0]["item_count"])

    async def test_manual_mark_delivered_persists_and_updates_data(self):
        fake = self._fake()
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Shipped",
            "Versendet: Example",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "Example"},
        )

        changed = await fake.async_mark_delivered(
            "123-4567890-1234567",
            delivered_at="manual",
        )

        self.assertTrue(changed)
        self.assertEqual("Delivered", fake._orders["123-4567890-1234567"]["status"])
        self.assertTrue(fake._orders["123-4567890-1234567"]["manual"])
        self.assertTrue(fake.saved)
        self.assertEqual("Delivered", fake.data[0]["status"])

    async def test_async_set_status_without_shipment_id_updates_all_shipments(self):
        fake = self._fake()
        order_id = "123-4567890-1234567"
        fake._upsert_order_event(
            order_id,
            "Shipped",
            "Versendet: First",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "First", "item_count": 2},
        )
        fake._upsert_order_event(
            order_id,
            "Out for delivery",
            "In Zustellung: Second",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Second", "item_count": 3},
        )

        changed = await fake.async_set_status(order_id, "Delivered")

        order = fake._orders[order_id]
        self.assertTrue(changed)
        self.assertEqual("Delivered", order["status"])
        self.assertTrue(order["manual"])
        self.assertEqual(5, order["item_count"])
        self.assertTrue(all(shipment["manual"] for shipment in order["shipments"]))
        self.assertEqual(
            {"Delivered"},
            {shipment["status"] for shipment in order["shipments"]},
        )
        self.assertEqual(5, fake.data[0]["item_count"])
        self.assertTrue(fake.saved)

    async def test_async_set_status_with_shipment_id_updates_only_target_shipment(self):
        fake = self._fake()
        order_id = "123-4567890-1234567"
        fake._upsert_order_event(
            order_id,
            "Shipped",
            "Versendet: First",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "First", "item_count": 2},
        )
        fake._upsert_order_event(
            order_id,
            "Shipped",
            "Versendet: Second",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Second", "item_count": 3},
        )
        first_shipment_id = fake._orders[order_id]["shipments"][0]["shipment_id"]

        changed = await fake.async_set_status(
            order_id,
            "Delivered",
            shipment_id=first_shipment_id,
        )

        order = fake._orders[order_id]
        first_shipment = fake._find_shipment(order, first_shipment_id)
        second_shipment = next(
            shipment
            for shipment in order["shipments"]
            if shipment["shipment_id"] != first_shipment_id
        )
        self.assertTrue(changed)
        self.assertEqual("Partially delivered", order["status"])
        self.assertTrue(order["manual"])
        self.assertEqual(5, order["item_count"])
        self.assertEqual("Delivered", first_shipment["status"])
        self.assertTrue(first_shipment["manual"])
        self.assertEqual("Shipped", second_shipment["status"])
        self.assertFalse(second_shipment["manual"])
        self.assertEqual(5, fake.data[0]["item_count"])
        self.assertTrue(fake.saved)

    async def test_ignore_and_restore_order(self):
        fake = self._fake()
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Shipped",
            "Versendet: Example",
            "2026-06-26T10:00:00+00:00",
            None,
            {"item_title": "Example"},
        )

        self.assertTrue(await fake.async_ignore_order("123-4567890-1234567"))
        self.assertEqual("Ignored", fake._orders["123-4567890-1234567"]["status"])
        self.assertTrue(await fake.async_restore_order("123-4567890-1234567"))
        self.assertEqual("Shipped", fake._orders["123-4567890-1234567"]["status"])

    def test_legacy_storage_shape_is_not_current_data(self):
        fake = self._fake()
        fake._orders = {
            "123-4567890-1234567": {
                "status": "Delivered",
                "updated": "2026-06-26T10:00:00+00:00",
            }
        }

        self.assertEqual([], fake._current_data())

    def test_statusless_update_does_not_resurrect_hidden_legacy_order(self):
        fake = self._fake()
        fake._orders = {
            "123-4567890-1234567": {
                "status": "Delivered",
                "updated": "2026-06-26T10:00:00+00:00",
                "item_title": "Legacy Example",
            }
        }

        outcome = fake._upsert_order_event_with_outcome(
            "123-4567890-1234567",
            None,
            "Lieferung aktualisiert: Legacy Example",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Legacy Example"},
        )

        self.assertEqual([], fake._current_data())
        self.assertNotIn("shipments", fake._orders["123-4567890-1234567"])
        self.assertFalse(outcome["changed"])
        self.assertFalse(outcome["enriched"])
        self.assertTrue(outcome["skipped_no_status"])

    def test_status_update_can_rebuild_hidden_legacy_order_as_2_0(self):
        fake = self._fake()
        fake._orders = {
            "123-4567890-1234567": {
                "status": "Delivered",
                "updated": "2026-06-26T10:00:00+00:00",
                "item_title": "Legacy Example",
            }
        }

        outcome = fake._upsert_order_event_with_outcome(
            "123-4567890-1234567",
            "Shipped",
            "Versendet: Legacy Example",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Legacy Example"},
        )

        current_data = fake._current_data()

        self.assertTrue(outcome["changed"])
        self.assertFalse(outcome["skipped_no_status"])
        self.assertEqual("Shipped", fake._orders["123-4567890-1234567"]["status"])
        self.assertEqual(1, len(fake._orders["123-4567890-1234567"]["shipments"]))
        self.assertEqual("Shipped", current_data[0]["status"])
        self.assertEqual(1, current_data[0]["shipment_count"])

    def test_lower_rank_email_enrichment_reports_status_regression_diagnostics(self):
        fake = self._fake()
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Out for delivery",
            "In Zustellung: Example",
            "2026-06-26T12:00:00+00:00",
            None,
            {"item_title": "Example"},
        )

        outcome = fake._upsert_order_event_with_outcome(
            "123-4567890-1234567",
            "Shipped",
            "Versendet: Example",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Example", "carrier": "DHL"},
        )
        scan_stats = coordinator._new_scan_stats(
            "INBOX",
            datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
        )
        coordinator._record_scan_outcome(scan_stats, outcome)

        shipment = fake._orders["123-4567890-1234567"]["shipments"][0]
        self.assertEqual("Out for delivery", shipment["status"])
        self.assertEqual("2026-06-26T12:00:00+00:00", shipment["updated"])
        self.assertEqual("DHL", shipment["carrier"])
        self.assertTrue(outcome["changed"])
        self.assertTrue(outcome["enriched"])
        self.assertTrue(outcome["skipped_status_regression"])
        self.assertFalse(outcome["skipped_older_duplicate"])
        self.assertEqual(1, scan_stats["updated_count"])
        self.assertEqual(1, scan_stats["enriched_count"])
        self.assertEqual(1, scan_stats["skipped_status_regression"])
        self.assertEqual(0, scan_stats["skipped_older_duplicate"])

    def test_older_duplicate_email_enrichment_reports_duplicate_diagnostics(self):
        fake = self._fake()
        fake._upsert_order_event(
            "123-4567890-1234567",
            "Out for delivery",
            "In Zustellung: Example",
            "2026-06-26T12:00:00+00:00",
            None,
            {"item_title": "Example"},
        )

        outcome = fake._upsert_order_event_with_outcome(
            "123-4567890-1234567",
            "Out for delivery",
            "In Zustellung: Example",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Example", "delivery_estimate": "heute"},
        )
        scan_stats = coordinator._new_scan_stats(
            "INBOX",
            datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
        )
        coordinator._record_scan_outcome(scan_stats, outcome)

        shipment = fake._orders["123-4567890-1234567"]["shipments"][0]
        self.assertEqual("Out for delivery", shipment["status"])
        self.assertEqual("2026-06-26T12:00:00+00:00", shipment["updated"])
        self.assertEqual("heute", shipment["delivery_estimate"])
        self.assertTrue(outcome["changed"])
        self.assertTrue(outcome["enriched"])
        self.assertFalse(outcome["skipped_status_regression"])
        self.assertTrue(outcome["skipped_older_duplicate"])
        self.assertEqual(1, scan_stats["updated_count"])
        self.assertEqual(1, scan_stats["enriched_count"])
        self.assertEqual(0, scan_stats["skipped_status_regression"])
        self.assertEqual(1, scan_stats["skipped_older_duplicate"])

    def test_statusless_older_delivery_update_keeps_newer_summary_and_duplicate_guard(self):
        fake = self._fake()
        order_id = "123-4567890-1234567"
        fake._upsert_order_event(
            order_id,
            "Delivered",
            "Zugestellt: First",
            "2026-06-26T12:00:00+00:00",
            None,
            {"item_title": "First"},
        )
        fake._upsert_order_event(
            order_id,
            "Shipped",
            "Versendet: Second",
            "2026-06-26T13:00:00+00:00",
            None,
            {"item_title": "Second"},
        )

        outcome = fake._upsert_order_event_with_outcome(
            order_id,
            None,
            "Lieferung aktualisiert: Second",
            "2026-06-26T11:00:00+00:00",
            None,
            {"item_title": "Second", "carrier": "DHL"},
        )
        scan_stats = coordinator._new_scan_stats(
            "INBOX",
            datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 26, 13, 0, tzinfo=timezone.utc),
        )
        coordinator._record_scan_outcome(scan_stats, outcome)

        order = fake._orders[order_id]
        second_shipment = fake._find_shipment(order, f"{order_id}:second")
        self.assertEqual("2026-06-26T13:00:00+00:00", second_shipment["updated"])
        self.assertEqual("2026-06-26T13:00:00+00:00", order["updated"])
        self.assertEqual("Second", order["item_title"])
        self.assertEqual("DHL", second_shipment["carrier"])
        self.assertTrue(outcome["changed"])
        self.assertTrue(outcome["enriched"])
        self.assertTrue(outcome["skipped_older_duplicate"])
        self.assertFalse(outcome["skipped_status_regression"])
        self.assertEqual(1, scan_stats["updated_count"])
        self.assertEqual(1, scan_stats["enriched_count"])
        self.assertEqual(1, scan_stats["skipped_older_duplicate"])


if __name__ == "__main__":
    unittest.main()
