"""Regression tests for Amazon order email parsing helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
import unittest


def _load_coordinator_module():
    """Load coordinator.py with minimal Home Assistant dependency stubs."""
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

    for name in ("const", "coordinator"):
        spec = importlib.util.spec_from_file_location(
            f"amazon_order_status.{name}",
            integration_dir / f"{name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"amazon_order_status.{name}"] = module
        spec.loader.exec_module(module)

    return sys.modules["amazon_order_status.coordinator"]


coordinator = _load_coordinator_module()


class ParserHelpersTest(unittest.TestCase):
    """German and English parser regression coverage."""

    def test_german_status_subjects(self):
        cases = {
            "Bestellt: Fitorb Smart Ring Pro - Das...": "Ordered",
            "Versendet: Fitorb Smart Ring Pro - Das...": "Shipped",
            "In Zustellung: Fitorb Smart Ring Pro - Das...": "Out for delivery",
            "Zugestellt: 1 Artikel | Bestellung # 306-2300519-2315556": "Delivered",
        }
        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                actual = coordinator.AmazonOrdersCoordinator._status_from_subject(
                    None,
                    subject.lower(),
                )
                self.assertEqual(expected, actual)

    def test_subject_item_matching_without_order_id(self):
        fake = coordinator.AmazonOrdersCoordinator.__new__(
            coordinator.AmazonOrdersCoordinator
        )
        fake._orders = {
            "304-1796910-0408363": {
                "status": "Ordered",
                "subject": "Bestellt: Fitorb Smart Ring Pro - Das...",
                "item_title": "Fitorb Smart Ring Pro - Das...",
                "updated": "2026-06-19T19:29:32+00:00",
                "tracking_url": None,
            }
        }

        self.assertEqual(
            ["304-1796910-0408363"],
            fake._order_ids_for_subject_item("Versendet: Fitorb Smart Ring Pro - Das..."),
        )
        self.assertEqual(
            ["304-1796910-0408363"],
            fake._order_ids_for_subject_item(
                "In Zustellung: Fitorb Smart Ring Pro - Das..."
            ),
        )

    def test_history_deduplicates_events(self):
        event = coordinator._history_entry(
            "Ordered",
            "Bestellt: Fitorb Smart Ring Pro - Das...",
            "2026-06-19T19:29:32+00:00",
            None,
        )
        history = coordinator._append_history(None, event)
        history = coordinator._append_history({"history": history}, event)

        self.assertEqual(1, len(history))
        self.assertEqual("Ordered", history[0]["status"])

    def test_status_ranking_prevents_regressions(self):
        self.assertLess(
            coordinator.STATUS_RANKS["Ordered"],
            coordinator.STATUS_RANKS["Shipped"],
        )
        self.assertLess(
            coordinator.STATUS_RANKS["Shipped"],
            coordinator.STATUS_RANKS["Out for delivery"],
        )
        self.assertLess(
            coordinator.STATUS_RANKS["Out for delivery"],
            coordinator.STATUS_RANKS["Delivered"],
        )

    def test_scan_stats_defaults_are_stable(self):
        since = datetime(2026, 6, 19, tzinfo=timezone.utc)
        now = datetime(2026, 6, 20, tzinfo=timezone.utc)

        stats = coordinator._new_scan_stats("INBOX", since, now)

        self.assertEqual("INBOX", stats["imap_folder"])
        self.assertEqual(since.isoformat(), stats["since"])
        self.assertEqual(now.isoformat(), stats["started"])
        self.assertIsNone(stats["error"])
        for key in (
            "email_count",
            "fetched_count",
            "recognized_count",
            "updated_count",
            "matched_by_subject_count",
            "skipped_no_order_id",
            "skipped_status_regression",
            "failed_fetch_count",
        ):
            self.assertEqual(0, stats[key])


if __name__ == "__main__":
    unittest.main()
