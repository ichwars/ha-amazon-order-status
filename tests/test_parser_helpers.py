"""Regression tests for Amazon order email parsing helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
import unittest


def _prepare_integration_package():
    """Register the integration package and simple dependency stubs."""
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

    return integration_dir


def _load_module(name: str, integration_dir: Path):
    """Load one integration module by name."""
    spec = importlib.util.spec_from_file_location(
        f"amazon_order_status.{name}",
        integration_dir / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"amazon_order_status.{name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_coordinator_module():
    """Load coordinator.py with minimal Home Assistant dependency stubs."""
    integration_dir = _prepare_integration_package()

    for name in ("const", "models", "parser", "coordinator"):
        _load_module(name, integration_dir)

    return sys.modules["amazon_order_status.coordinator"]


def _load_parser_module():
    """Load parser.py and models.py without coordinator dependencies."""
    integration_dir = _prepare_integration_package()
    _load_module("models", integration_dir)
    return _load_module("parser", integration_dir)


parser = _load_parser_module()
_COORDINATOR = None


def coordinator_module():
    """Load coordinator.py only for tests that need it."""
    global _COORDINATOR  # noqa: PLW0603
    if _COORDINATOR is None:
        _COORDINATOR = _load_coordinator_module()
    return _COORDINATOR


class ParserHelpersTest(unittest.TestCase):
    """German and English parser regression coverage."""

    def test_german_status_subjects(self):
        coordinator = coordinator_module()
        cases = {
            "Bestellt: Fitorb Smart Ring Pro - Das...": "Ordered",
            "Versendet: Fitorb Smart Ring Pro - Das...": "Shipped",
            "In Zustellung: Fitorb Smart Ring Pro - Das...": "Out for delivery",
            "Zustellversuch: 2 SUNLU ASA Filament 1.75mm,...": "Delivery attempted",
            "Zugestellt: 1 Artikel | Bestellung # 306-2300519-2315556": "Delivered",
        }
        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                actual = coordinator.AmazonOrdersCoordinator._status_from_subject(
                    None,
                    subject.lower(),
                )
                self.assertEqual(expected, actual)

    def test_new_status_subjects(self):
        cases = {
            "Abholbereit: Example ist in deiner Amazon Locker Abholstation": "Pickup ready",
            "Lieferung ist verspätet: Example": "Delayed",
            "Problem mit deiner Lieferung: Example": "Delivery problem",
            "Unzustellbar: Example": "Undeliverable",
            "Storniert: Deine Amazon-Bestellung": "Canceled",
            "Rücksendung gestartet: Example": "Return started",
            "Erstattung veranlasst: Example": "Refunded",
            "Pickup available: Example is ready for pickup": "Pickup ready",
            "Your package is running late": "Delayed",
            "Action required for your delivery": "Delivery problem",
            "Undeliverable package": "Undeliverable",
            "Cancelled: your Amazon order": "Canceled",
            "Return started for Example": "Return started",
            "Refund issued for Example": "Refunded",
        }
        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                self.assertEqual(
                    expected,
                    parser.status_from_subject(subject.lower()),
                )

    def test_subject_item_matching_without_order_id(self):
        coordinator = coordinator_module()
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

    def test_delivered_count_subject_is_not_treated_as_item_title(self):
        self.assertIsNone(
            parser.extract_item_title(
                "Zugestellt: 1\u202fArtikel\u202f|\u202fBestellung\u202f#\u202f306-2300519-2315556"
            )
        )

    def test_subject_item_matching_skips_ambiguous_items(self):
        coordinator = coordinator_module()
        fake = coordinator.AmazonOrdersCoordinator.__new__(
            coordinator.AmazonOrdersCoordinator
        )
        fake._orders = {
            "304-1111111-1111111": {
                "status": "Ordered",
                "item_title": "Fitorb Smart Ring Pro",
            },
            "304-2222222-2222222": {
                "status": "Shipped",
                "item_title": "Fitorb Smart Ring Pro",
            },
            "304-3333333-3333333": {
                "status": "Delivered",
                "item_title": "Fitorb Smart Ring Pro",
            },
        }

        self.assertEqual(
            ["304-1111111-1111111", "304-2222222-2222222"],
            fake._order_ids_for_subject_item("Versendet: Fitorb Smart Ring Pro"),
        )

    def test_message_sender_must_be_amazon_domain(self):
        amazon_msg = EmailMessage()
        amazon_msg["From"] = "Amazon.de <shipment-tracking@amazon.de>"
        phishing_msg = EmailMessage()
        phishing_msg["From"] = "Amazon.de <shipment-tracking@amazon.de.evil.test>"

        self.assertTrue(parser.message_from_amazon(amazon_msg))
        self.assertFalse(parser.message_from_amazon(phishing_msg))

    def test_safe_amazon_url_rejects_non_amazon_hosts(self):
        self.assertEqual(
            "https://www.amazon.de/gp/r.html?x=1",
            parser.safe_amazon_url("https://www.amazon.de/gp/r.html?x=1"),
        )
        self.assertIsNone(
            parser.safe_amazon_url("https://www.amazon.de.evil.test/gp/r.html")
        )
        self.assertIsNone(parser.safe_amazon_url("http://www.amazon.de/gp/r.html"))

    def test_history_deduplicates_events(self):
        coordinator = coordinator_module()
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
        coordinator = coordinator_module()
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
            coordinator.STATUS_RANKS["Delivery attempted"],
        )
        self.assertLess(
            coordinator.STATUS_RANKS["Delivery attempted"],
            coordinator.STATUS_RANKS["Delivered"],
        )

    def test_existing_order_can_be_enriched_from_older_email(self):
        coordinator = coordinator_module()
        existing = {
            "status": "Delivered",
            "item_title": None,
            "updated": "2026-06-19T14:15:55+00:00",
            "tracking_url": None,
        }
        body_details = {
            "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
            "delivery_estimate": "24. Juni - 25. Juni",
        }

        changed = coordinator._enrich_missing_order_details(
            existing,
            body_details,
            item_title="Example Product",
            tracking_url="https://www.amazon.de/gp/r.html?x=1",
        )

        self.assertTrue(changed)
        self.assertEqual("Delivered", existing["status"])
        self.assertEqual("Example Product", existing["item_title"])
        self.assertEqual(
            "https://m.media-amazon.com/images/I/example.jpg",
            existing["item_image_url"],
        )
        self.assertEqual("24. Juni - 25. Juni", existing["delivery_estimate"])
        self.assertEqual(
            "https://www.amazon.de/gp/r.html?x=1",
            existing["tracking_url"],
        )

    def test_body_details_extract_delivery_window_title_count_and_image(self):
        details = parser.parse_body_details(
            "Bestellt: Fitorb Smart Ring Pro - Das...",
            "Vielen Dank fuer deine Bestellung!\nZustellung: 24. Juni - 25. Juni\n1 Artikel",
            """
            <html>
              <body>
                <img src="https://m.media-amazon.com/images/G/01/outbound/etc/pixel.gif"
                     width="19" height="19" alt="Ausstehend">
                <a href="https://www.amazon.de/gp/r.html?x=1">
                  <img src="https://m.media-amazon.com/images/I/71P8Vt3O5-L._SS90_.jpg"
                       width="122"
                       alt="Fitorb Smart Ring Pro - Das Original. High-Tech Fitnessring">
                  Fitorb Smart Ring Pro - Das Origi...
                </a>
              </body>
            </html>
            """,
            include_debug=True,
        )

        self.assertEqual(
            "Fitorb Smart Ring Pro - Das Original. High-Tech Fitnessring",
            details["item_title"],
        )
        self.assertEqual("24. Juni - 25. Juni", details["delivery_estimate"])
        self.assertEqual(1, details["item_count"])
        self.assertEqual(
            "https://m.media-amazon.com/images/I/71P8Vt3O5-L._SS90_.jpg",
            details["item_image_url"],
        )
        self.assertEqual("body_details", details["parser_debug"]["source"])
        self.assertNotIn("306-2300519-2315556", str(details["parser_debug"]))

    def test_body_details_extract_delivery_attempt_and_delivery_window(self):
        details = parser.parse_body_details(
            "Zustellversuch: 2 SUNLU ASA Filament 1.75mm,...",
            "Deine Zustellung wurde versucht\nVersuchte Zustellung heute um 11:04",
            """
            <img src="https://m.media-amazon.com/images/I/71FVTr5YE3L._SS90_.jpg"
                 width="122"
                 alt="SUNLU ASA Filament 1.75mm, UV Regen Hitzebestaendig">
            """,
            include_debug=False,
        )

        self.assertEqual("heute um 11:04", details["delivered_at"])
        self.assertEqual(
            "SUNLU ASA Filament 1.75mm, UV Regen Hitzebestaendig",
            details["item_title"],
        )
        self.assertNotIn("parser_debug", details)

    def test_body_details_rejects_non_amazon_image_hosts(self):
        details = parser.parse_body_details(
            "Bestellt: Example",
            "Zustellung: morgen",
            '<img src="https://www.amazon.de.evil.test/image.jpg" width="122" alt="Example">',
            include_debug=True,
        )

        self.assertNotIn("item_image_url", details)
        self.assertEqual("morgen", details["delivery_estimate"])

    def test_delivery_update_subject_is_recognized_without_status_regression(self):
        coordinator = coordinator_module()
        subject = (
            "Aktualisierung der voraussichtlichen Lieferung fuer deine "
            "Amazon.com-Bestellung mit der Nummer 306-9382035-6671562"
        )

        self.assertIsNone(
            coordinator.AmazonOrdersCoordinator._status_from_subject(
                None,
                subject.lower(),
            )
        )
        self.assertTrue(parser.is_delivery_update_subject(subject.lower()))

    def test_structured_relative_delivery_dates(self):
        received = datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc)

        today = parser.parse_body_details(
            "In Zustellung: Example",
            "Ankunft heute 15h - 19h",
            "",
            received_at=received,
        )
        tomorrow = parser.parse_body_details(
            "Versendet: Example",
            "Arriving tomorrow 8:00 - 12:00",
            "",
            received_at=received,
        )

        self.assertEqual("2026-06-26", today["delivery_date_start"])
        self.assertEqual("2026-06-26", today["delivery_date_end"])
        self.assertEqual("15:00", today["delivery_window_start"])
        self.assertEqual("19:00", today["delivery_window_end"])
        self.assertEqual("2026-06-27", tomorrow["delivery_date_start"])
        self.assertEqual("08:00", tomorrow["delivery_window_start"])

    def test_delivery_delay_flag_refreshes_on_later_non_delayed_update(self):
        received = datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc)

        delayed = parser.parse_body_details(
            "Lieferung ist verspätet: Example",
            "Lieferung ist verspätet",
            "",
            received_at=received,
        )
        refreshed = parser.parse_body_details(
            "In Zustellung: Example",
            "Ankunft heute 15h - 19h",
            "",
            received_at=received,
        )

        self.assertTrue(delayed["delivery_is_delayed"])
        self.assertEqual("verzögert", delayed["delivery_estimate"])
        self.assertFalse(refreshed["delivery_is_delayed"])
        self.assertEqual("2026-06-26", refreshed["delivery_date_start"])
        self.assertEqual("2026-06-26", refreshed["delivery_date_end"])
        self.assertEqual("15:00", refreshed["delivery_window_start"])
        self.assertEqual("19:00", refreshed["delivery_window_end"])

    def test_structured_german_date_range(self):
        details = parser.parse_body_details(
            "Bestellt: Example",
            "Zustellung: 24. Juni - 25. Juni",
            "",
            received_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        )

        self.assertEqual("24. Juni - 25. Juni", details["delivery_estimate"])
        self.assertEqual("2026-06-24", details["delivery_date_start"])
        self.assertEqual("2026-06-25", details["delivery_date_end"])

    def test_structured_date_rolls_to_next_year_after_new_year(self):
        details = parser.parse_body_details(
            "Bestellt: Example",
            "Zustellung: 2. Januar",
            "",
            received_at=datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc),
        )

        self.assertEqual("2. Januar", details["delivery_estimate"])
        self.assertEqual("2027-01-02", details["delivery_date_start"])
        self.assertEqual("2027-01-02", details["delivery_date_end"])

    def test_scan_stats_defaults_are_stable(self):
        coordinator = coordinator_module()
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
            "skipped_sender",
            "skipped_ambiguous_subject_match",
            "skipped_status_regression",
            "failed_fetch_count",
        ):
            self.assertEqual(0, stats[key])

    def test_scan_without_order_status_emails_logs_debug_not_warning(self):
        coordinator = coordinator_module()
        calls = []

        original_debug = coordinator._LOGGER.debug
        original_warning = coordinator._LOGGER.warning

        def fake_debug(message, *args):
            calls.append(("debug", message % args))

        def fake_warning(message, *args):
            calls.append(("warning", message % args))

        coordinator._LOGGER.debug = fake_debug
        coordinator._LOGGER.warning = fake_warning
        try:
            coordinator._log_scan_without_order_status(
                {"email_count": 4, "recognized_count": 0},
                "INBOX",
            )
        finally:
            coordinator._LOGGER.debug = original_debug
            coordinator._LOGGER.warning = original_warning

        self.assertEqual(1, len(calls))
        self.assertEqual("debug", calls[0][0])
        self.assertIn("recognized no order status emails", calls[0][1])

    def test_search_failure_returns_unsuccessful_scan_result(self):
        coordinator = coordinator_module()
        class SearchFailMail:
            def login(self, _email, _password):
                return "OK", []

            def select(self, _folder):
                return "OK", []

            def search(self, *_args):
                return "NO", []

            def logout(self):
                self.logged_out = True

        mail = SearchFailMail()
        fake = coordinator.AmazonOrdersCoordinator.__new__(
            coordinator.AmazonOrdersCoordinator
        )
        fake.entry = SimpleNamespace(
            data={
                "email": "user@example.com",
                "password": "secret",
                "imap_server": "imap.example.com",
            }
        )
        fake._mark_as_read = False
        fake._initial_scan_days = 14
        fake._imap_folder = "INBOX"
        fake._require_amazon_sender = True

        original_imap = coordinator.imaplib.IMAP4_SSL
        coordinator.imaplib.IMAP4_SSL = lambda *_args: mail
        try:
            now = datetime(2026, 6, 20, tzinfo=timezone.utc)
            result = fake._fetch_and_parse_emails(None, now)
        finally:
            coordinator.imaplib.IMAP4_SSL = original_imap

        self.assertFalse(result.success)
        self.assertEqual("imap_search_failed", result.error)
        self.assertEqual("imap_search_failed", fake.last_scan_stats["error"])
        self.assertTrue(mail.logged_out)


if __name__ == "__main__":
    unittest.main()
