# Amazon Order Status 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the breaking 2.0 shipment-first Amazon Order Status integration with expanded statuses, structured delivery details, manual workflow services, migration-by-rescan documentation, and release metadata.

**Architecture:** Split the current order-centric coordinator into focused model and parser helpers, then adapt coordinator storage, sensors, services, and docs around the new order -> shipments -> items contract. The 2.0 coordinator ignores legacy 1.x stored active data and expects users to rebuild state with `amazon_order_status.rescan` and `clear_existing: true`.

**Tech Stack:** Home Assistant custom integration, Python 3.14-compatible code, stdlib `unittest`, Home Assistant `DataUpdateCoordinator`, `Store`, `SensorEntity`, `voluptuous`, and existing `beautifulsoup4`.

## Global Constraints

- Release version must be `2.0.0`.
- Do not store raw email body text, sender addresses, payment amounts, or third-party tracking numbers.
- Tracking URLs must remain validated HTTPS Amazon-domain URLs only.
- Existing privacy toggles continue to filter nested order and shipment attributes.
- Legacy 1.x storage is not migrated into current sensor data; users rebuild with `amazon_order_status.rescan` and `clear_existing: true`.
- No external network calls or carrier API calls are added.
- Every production behavior change must have a failing test before implementation.
- Keep Home Assistant entity IDs predictable by using status keys under `sensor.amazon_orders_*`.

---

## File Structure

- Create `custom_components/amazon_order_status/models.py`: status constants, rollup helpers, shipment/order builders, manual/ignored mutations.
- Create `custom_components/amazon_order_status/parser.py`: text cleanup, language profiles, Amazon URL checks, order ID extraction, body detail parsing, structured date/window parsing.
- Modify `custom_components/amazon_order_status/coordinator.py`: import parser/model helpers, store version 2, clean storage rebuild, shipment-aware upserts, manual workflow methods.
- Modify `custom_components/amazon_order_status/sensor.py`: new status sensors, nested shipment privacy filtering, shipment counts.
- Modify `custom_components/amazon_order_status/const.py`: new service names and attributes.
- Modify `custom_components/amazon_order_status/__init__.py`: register and route new services.
- Modify `custom_components/amazon_order_status/services.yaml`: service schemas for manual workflows.
- Modify `custom_components/amazon_order_status/translations/en.json` and `custom_components/amazon_order_status/translations/de.json`: new services and fields.
- Modify `custom_components/amazon_order_status/manifest.json`: bump to `2.0.0`.
- Modify `README.md` and `CHANGELOG.md`: breaking upgrade, rescan migration, new dashboard example.
- Create `tests/test_models.py`: model rollup and mutation tests.
- Modify `tests/test_parser_helpers.py`: parser imports and expanded status/date coverage.
- Create `tests/test_coordinator_state.py`: coordinator storage/upsert/manual tests with stubs.
- Modify `tests/test_sensor_helpers.py`: nested privacy filtering and new status sensor coverage.
- Modify `tests/test_translations.py`: new service translation coverage.

---

### Task 1: Model Helpers

**Files:**
- Create: `custom_components/amazon_order_status/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `ORDER_STATUSES: tuple[str, ...]`
  - `SHIPMENT_STATUSES: tuple[str, ...]`
  - `STATUS_SENSOR_DEFINITIONS: tuple[tuple[str, str, str], ...]`
  - `ORDER_DETAIL_FIELDS: tuple[str, ...]`
  - `shipment_id_for(order_id: str, item_key: str | None, tracking_url: str | None) -> str`
  - `new_history_event(status: str, updated: str, subject: str | None = None, tracking_url: str | None = None, reason: str | None = None) -> dict[str, Any]`
  - `append_history(existing: list[dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]]`
  - `rollup_order_status(shipments: list[dict[str, Any]], ignored: bool = False) -> str`
  - `build_shipment(order_id: str, status: str, updated: str, subject: str, item_key: str | None, item_title: str | None, tracking_url: str | None, details: dict[str, Any]) -> dict[str, Any]`
  - `build_order(order_id: str, shipment: dict[str, Any], subject: str, updated: str) -> dict[str, Any]`
  - `upsert_shipment(order: dict[str, Any], shipment: dict[str, Any]) -> dict[str, Any]`
  - `set_manual_status(order: dict[str, Any], status: str, updated: str, shipment_id: str | None = None, delivered_at: str | None = None) -> bool`
  - `set_ignored(order: dict[str, Any], ignored: bool, updated: str, shipment_id: str | None = None) -> bool`
- Consumes: no project-local helpers.

- [ ] **Step 1: Write model failing tests**

Add `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run model test to verify it fails**

Run: `python -m unittest tests.test_models`

Expected: FAIL because `custom_components/amazon_order_status/models.py` does not exist.

- [ ] **Step 3: Implement `models.py`**

Create `custom_components/amazon_order_status/models.py` with constants and functions matching the interfaces. Implement `rollup_order_status` with the exact priority order from the design spec. Use deterministic `shipment_id_for` by combining order ID with normalized item key when present, otherwise a sanitized tracking URL suffix, otherwise `order_id:default`.

- [ ] **Step 4: Run model tests to verify pass**

Run: `python -m unittest tests.test_models`

Expected: PASS.

- [ ] **Step 5: Commit model helpers**

Run:

```bash
git add custom_components/amazon_order_status/models.py tests/test_models.py
git commit -m "Add 2.0 order shipment model helpers"
```

---

### Task 2: Parser Split And Structured Delivery Details

**Files:**
- Create: `custom_components/amazon_order_status/parser.py`
- Modify: `tests/test_parser_helpers.py`

**Interfaces:**
- Consumes: `ORDER_DETAIL_FIELDS` from `models.py`
- Produces:
  - `extract_order_ids_from_text(*texts: str) -> list[str]`
  - `safe_amazon_url(href: str | None) -> str | None`
  - `safe_amazon_image_url(src: str | None) -> str | None`
  - `message_from_amazon(msg) -> bool`
  - `status_from_subject(subject: str) -> str | None`
  - `is_delivery_update_subject(subject_lower: str) -> bool`
  - `extract_item_title(subject: str) -> str | None`
  - `normalize_item_key(item_title: str | None) -> str | None`
  - `parse_body_details(subject: str, body_text: str, html_body: str, received_at: datetime | None = None, include_debug: bool = False) -> dict[str, Any]`

- [ ] **Step 1: Update parser tests for the new module and statuses**

Modify the loader in `tests/test_parser_helpers.py` so it imports `amazon_order_status.models` and `amazon_order_status.parser`. Keep `coordinator` loading only for tests that exercise coordinator methods.

Add tests:

```python
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
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run: `python -m unittest tests.test_parser_helpers`

Expected: FAIL because `parser.py` does not exist and new statuses are not recognized.

- [ ] **Step 3: Implement `parser.py`**

Move the existing parser helpers out of `coordinator.py` into `parser.py`, preserving behavior for existing tests. Add new status patterns and structured date/window extraction. Keep compatibility wrappers in `coordinator.py` temporarily if existing tests reference old private names.

- [ ] **Step 4: Run parser tests to verify pass**

Run: `python -m unittest tests.test_parser_helpers`

Expected: PASS.

- [ ] **Step 5: Commit parser split**

Run:

```bash
git add custom_components/amazon_order_status/parser.py custom_components/amazon_order_status/coordinator.py tests/test_parser_helpers.py
git commit -m "Add 2.0 parser status and delivery detail support"
```

---

### Task 3: Coordinator 2.0 Storage And Shipment Upserts

**Files:**
- Modify: `custom_components/amazon_order_status/coordinator.py`
- Create: `tests/test_coordinator_state.py`

**Interfaces:**
- Consumes: `models.py` and `parser.py`.
- Produces coordinator methods:
  - `async_set_status(order_id: str, status: str, shipment_id: str | None = None) -> bool`
  - `async_mark_delivered(order_id: str, shipment_id: str | None = None, delivered_at: str | None = None) -> bool`
  - `async_ignore_order(order_id: str, shipment_id: str | None = None) -> bool`
  - `async_restore_order(order_id: str, shipment_id: str | None = None) -> bool`
  - `_upsert_order_event(order_id: str, status: str | None, subject: str, updated_ts: str, tracking_url: str | None, body_details: dict[str, Any]) -> bool`

- [ ] **Step 1: Write failing coordinator state tests**

Create `tests/test_coordinator_state.py`:

```python
"""Regression tests for Amazon Order Status 2.0 coordinator state handling."""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run coordinator tests to verify failure**

Run: `python -m unittest tests.test_coordinator_state`

Expected: FAIL because 2.0 coordinator methods and legacy filtering do not exist.

- [ ] **Step 3: Implement coordinator 2.0 state**

Set `STORAGE_VERSION = 2`. Change `_current_data` so it returns only orders with a `shipments` list. Change `_fetch_and_parse_emails` to call parser helpers and `_upsert_order_event`. Keep IMAP connection behavior unchanged. Implement async manual workflow methods that save state and refresh coordinator data.

- [ ] **Step 4: Run coordinator state tests**

Run: `python -m unittest tests.test_coordinator_state`

Expected: PASS.

- [ ] **Step 5: Run parser/model tests for regression**

Run: `python -m unittest tests.test_models tests.test_parser_helpers`

Expected: PASS.

- [ ] **Step 6: Commit coordinator 2.0 state**

Run:

```bash
git add custom_components/amazon_order_status/coordinator.py tests/test_coordinator_state.py
git commit -m "Add 2.0 coordinator shipment state"
```

---

### Task 4: Sensor Contract And Nested Privacy Filtering

**Files:**
- Modify: `custom_components/amazon_order_status/sensor.py`
- Modify: `tests/test_sensor_helpers.py`

**Interfaces:**
- Consumes: `STATUS_SENSOR_DEFINITIONS` from `models.py`.
- Produces:
  - status sensors for every 2.0 order rollup status.
  - `_build_exposed_order(coordinator, data) -> dict[str, Any]` with filtered nested `shipments`.
  - `_filtered_shipments(coordinator, shipments) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write failing sensor tests**

Add tests to `tests/test_sensor_helpers.py`:

```python
    def test_nested_shipments_respect_privacy_options(self):
        coordinator = SimpleNamespace(
            expose_order_id=False,
            expose_item_title=False,
            expose_tracking_url=False,
            expose_delivery_details=False,
            expose_carrier=False,
            expose_item_image=False,
            expose_parser_debug=False,
        )
        data = {
            "order_id": "123-4567890-1234567",
            "status": "Partially delivered",
            "updated": "2026-06-26T12:00:00+00:00",
            "shipments": [
                {
                    "shipment_id": "123-4567890-1234567:first",
                    "status": "Delivered",
                    "item_title": "Private title",
                    "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
                    "carrier": "DHL",
                    "delivery_estimate": "heute",
                    "delivery_date_start": "2026-06-26",
                    "delivery_date_end": "2026-06-26",
                    "delivery_window_start": "15:00",
                    "delivery_window_end": "19:00",
                    "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
                    "updated": "2026-06-26T12:00:00+00:00",
                    "history": [],
                    "manual": False,
                    "ignored": False,
                }
            ],
            "history": [],
            "manual": False,
            "ignored": False,
        }

        order = sensor._build_exposed_order(coordinator, data)

        self.assertEqual(
            {"status", "updated", "shipment_count", "shipments", "history", "manual", "ignored"},
            set(order),
        )
        self.assertEqual(
            {"shipment_id", "status", "updated", "history", "manual", "ignored"},
            set(order["shipments"][0]),
        )

    def test_nested_shipments_expose_opted_in_details(self):
        coordinator = SimpleNamespace(
            expose_order_id=True,
            expose_item_title=True,
            expose_tracking_url=True,
            expose_delivery_details=True,
            expose_carrier=True,
            expose_item_image=True,
            expose_parser_debug=False,
        )
        data = {
            "order_id": "123-4567890-1234567",
            "status": "Delayed",
            "subject": "Lieferung ist verspätet: Example",
            "last_subject": "Lieferung ist verspätet: Example",
            "updated": "2026-06-26T12:00:00+00:00",
            "shipments": [
                {
                    "shipment_id": "123-4567890-1234567:example",
                    "status": "Delayed",
                    "item_title": "Example",
                    "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
                    "carrier": "DHL",
                    "delivery_estimate": "verzögert",
                    "delivery_date_start": None,
                    "delivery_date_end": None,
                    "delivery_window": None,
                    "delivery_window_start": None,
                    "delivery_window_end": None,
                    "delivery_is_delayed": True,
                    "item_count": 1,
                    "item_image_url": None,
                    "updated": "2026-06-26T12:00:00+00:00",
                    "history": [],
                    "manual": False,
                    "ignored": False,
                }
            ],
            "history": [],
            "manual": False,
            "ignored": False,
        }

        order = sensor._build_exposed_order(coordinator, data)

        self.assertEqual("123-4567890-1234567", order["order_id"])
        self.assertEqual("Example", order["shipments"][0]["item_title"])
        self.assertTrue(order["shipments"][0]["delivery_is_delayed"])
        self.assertIsNone(order["shipments"][0]["delivery_date_start"])
```

- [ ] **Step 2: Run sensor tests to verify failure**

Run: `python -m unittest tests.test_sensor_helpers`

Expected: FAIL because nested shipment filtering and 2.0 sensors do not exist.

- [ ] **Step 3: Implement sensor contract**

Import `STATUS_SENSOR_DEFINITIONS`. Replace `SENSORS` with definitions from models. Include `shipment_count` in status attributes. Build nested shipment payloads with privacy filtering. Keep last-updated diagnostic sensor unchanged.

- [ ] **Step 4: Run sensor tests to verify pass**

Run: `python -m unittest tests.test_sensor_helpers`

Expected: PASS.

- [ ] **Step 5: Commit sensor contract**

Run:

```bash
git add custom_components/amazon_order_status/sensor.py tests/test_sensor_helpers.py
git commit -m "Expose 2.0 shipment sensor contract"
```

---

### Task 5: Manual Workflow Services

**Files:**
- Modify: `custom_components/amazon_order_status/const.py`
- Modify: `custom_components/amazon_order_status/__init__.py`
- Modify: `custom_components/amazon_order_status/services.yaml`
- Modify: `custom_components/amazon_order_status/translations/en.json`
- Modify: `custom_components/amazon_order_status/translations/de.json`
- Modify: `tests/test_translations.py`

**Interfaces:**
- Consumes coordinator async methods from Task 3.
- Produces service constants:
  - `SERVICE_SET_STATUS = "set_status"`
  - `SERVICE_MARK_DELIVERED = "mark_delivered"`
  - `SERVICE_IGNORE_ORDER = "ignore_order"`
  - `SERVICE_RESTORE_ORDER = "restore_order"`
  - `ATTR_STATUS = "status"`
  - `ATTR_SHIPMENT_ID = "shipment_id"`
  - `ATTR_DELIVERED_AT = "delivered_at"`

- [ ] **Step 1: Write failing translation/schema tests**

Extend `tests/test_translations.py` so required service keys include:

```python
REQUIRED_SERVICE_KEYS = {
    "purge_order",
    "rescan",
    "set_status",
    "mark_delivered",
    "ignore_order",
    "restore_order",
}
```

Add field checks for `order_id`, `shipment_id`, `status`, `delivered_at`, and `config_entry_id` where each service requires them.

- [ ] **Step 2: Run translation tests to verify failure**

Run: `python -m unittest tests.test_translations`

Expected: FAIL because new service translations are missing.

- [ ] **Step 3: Implement service constants, schemas, handlers, YAML, translations**

Add schemas in `__init__.py`:

```python
SET_STATUS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Required(ATTR_STATUS): vol.In(ORDER_STATUSES),
        vol.Optional(ATTR_SHIPMENT_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)
```

Add equivalent schemas for mark delivered, ignore, and restore. Register and remove all services alongside existing services. Handlers must raise `HomeAssistantError` when no matching order or shipment is found.

- [ ] **Step 4: Run translation tests**

Run: `python -m unittest tests.test_translations`

Expected: PASS.

- [ ] **Step 5: Run import compile check**

Run:

```bash
python -m py_compile custom_components/amazon_order_status/__init__.py custom_components/amazon_order_status/const.py
```

Expected: exit code 0.

- [ ] **Step 6: Commit service workflows**

Run:

```bash
git add custom_components/amazon_order_status/const.py custom_components/amazon_order_status/__init__.py custom_components/amazon_order_status/services.yaml custom_components/amazon_order_status/translations/en.json custom_components/amazon_order_status/translations/de.json tests/test_translations.py
git commit -m "Add 2.0 manual workflow services"
```

---

### Task 6: Documentation, Dashboard, And Release Metadata

**Files:**
- Modify: `custom_components/amazon_order_status/manifest.json`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes completed runtime contract from Tasks 1-5.
- Produces release version `2.0.0` and migration documentation.

- [ ] **Step 1: Write documentation checks**

Add or extend tests to assert `manifest.json` version equals `2.0.0` and README contains:

```text
clear_existing: true
shipments
sensor.amazon_orders_partially_delivered
amazon_order_status.set_status
amazon_order_status.mark_delivered
amazon_order_status.ignore_order
amazon_order_status.restore_order
```

Place this in `tests/test_translations.py` or create `tests/test_release_docs.py`.

- [ ] **Step 2: Run documentation tests to verify failure**

Run: `python -m unittest tests.test_release_docs`

Expected: FAIL until docs and manifest are updated.

- [ ] **Step 3: Update manifest, README, and changelog**

Set manifest version to `2.0.0`. Add changelog section `## 2.0.0` with breaking change notes. Replace or augment the dashboard example with a German-first nested shipment dashboard that uses only `o.get(...)` and `s.get(...)` access.

- [ ] **Step 4: Run docs tests to verify pass**

Run: `python -m unittest tests.test_release_docs`

Expected: PASS.

- [ ] **Step 5: Commit docs and release metadata**

Run:

```bash
git add custom_components/amazon_order_status/manifest.json README.md CHANGELOG.md tests/test_release_docs.py
git commit -m "Document Amazon Order Status 2.0 migration"
```

---

### Task 7: Full Verification And Release Prep

**Files:**
- Review all modified files.

**Interfaces:**
- Consumes all previous tasks.
- Produces a verified 2.0-ready worktree.

- [ ] **Step 1: Run full test suite**

Run: `python -m unittest discover -s tests`

Expected: all tests pass.

- [ ] **Step 2: Run JSON validation**

Run:

```bash
python -m json.tool custom_components/amazon_order_status/manifest.json
python -m json.tool hacs.json
python -m json.tool custom_components/amazon_order_status/translations/en.json
python -m json.tool custom_components/amazon_order_status/translations/de.json
```

Expected: all commands exit 0.

- [ ] **Step 3: Run compile validation**

Run:

```bash
python -m py_compile custom_components/amazon_order_status/__init__.py custom_components/amazon_order_status/config_flow.py custom_components/amazon_order_status/const.py custom_components/amazon_order_status/coordinator.py custom_components/amazon_order_status/models.py custom_components/amazon_order_status/options_flow.py custom_components/amazon_order_status/parser.py custom_components/amazon_order_status/sensor.py
```

Expected: exit code 0.

- [ ] **Step 4: Run diff whitespace check**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Remove generated caches**

If test or compile commands create `__pycache__`, remove only resolved paths inside the workspace:

```powershell
$repo = (Resolve-Path '.').Path
$targets = @('custom_components\amazon_order_status\__pycache__', 'tests\__pycache__') | ForEach-Object { Resolve-Path $_ -ErrorAction SilentlyContinue }
foreach ($target in $targets) {
    if (-not $target.Path.StartsWith($repo + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to remove outside workspace: $($target.Path)"
    }
}
foreach ($target in $targets) {
    Remove-Item -LiteralPath $target.Path -Recurse -Force
}
```

- [ ] **Step 6: Prepare final release commit if needed**

If verification changed docs or cleanup state, commit the remaining intended files:

```bash
git status -sb
git add CHANGELOG.md README.md custom_components/amazon_order_status/__init__.py custom_components/amazon_order_status/const.py custom_components/amazon_order_status/coordinator.py custom_components/amazon_order_status/manifest.json custom_components/amazon_order_status/models.py custom_components/amazon_order_status/parser.py custom_components/amazon_order_status/sensor.py custom_components/amazon_order_status/services.yaml custom_components/amazon_order_status/translations/en.json custom_components/amazon_order_status/translations/de.json tests/test_coordinator_state.py tests/test_models.py tests/test_parser_helpers.py tests/test_release_docs.py tests/test_sensor_helpers.py tests/test_translations.py
git commit -m "Release 2.0.0"
```

Expected: the working tree is clean except for expected unpushed commits.

- [ ] **Step 7: Publish after user confirmation**

After final verification, push `main`, create annotated tag `2.0.0`, push the tag, and create the GitHub release on `ichwars/ha-amazon-order-status` with release notes copied from `CHANGELOG.md`.

Run:

```bash
git push origin main
git tag -a 2.0.0 -m "Release 2.0.0"
git push origin 2.0.0
gh release create 2.0.0 -R ichwars/ha-amazon-order-status --title "2.0.0" --notes-file release-notes-2.0.0.md --verify-tag
```

Expected: GitHub release URL for `2.0.0`.
