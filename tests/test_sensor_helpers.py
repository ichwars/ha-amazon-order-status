"""Regression tests for Amazon order sensor attribute filtering."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import types
import unittest


def _load_sensor_module():
    """Load sensor.py with minimal Home Assistant dependency stubs."""
    components_sensor = types.ModuleType("homeassistant.components.sensor")

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    class SensorEntity:
        pass

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: str | None = None
        device_class: str | None = None

    components_sensor.SensorDeviceClass = SensorDeviceClass
    components_sensor.SensorEntity = SensorEntity
    components_sensor.SensorEntityDescription = SensorEntityDescription

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    const = types.ModuleType("homeassistant.const")
    const.EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddConfigEntryEntitiesCallback = object
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = CoordinatorEntity

    sys.modules.update(
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.components": types.ModuleType("homeassistant.components"),
            "homeassistant.components.sensor": components_sensor,
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
            "homeassistant.helpers.device_registry": device_registry,
            "homeassistant.helpers.entity_platform": entity_platform,
            "homeassistant.helpers.update_coordinator": update_coordinator,
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

    for name in ("const", "coordinator", "models", "sensor"):
        if name == "coordinator":
            module = types.ModuleType("amazon_order_status.coordinator")
            module.AmazonOrdersCoordinator = object
            sys.modules["amazon_order_status.coordinator"] = module
            continue

        spec = importlib.util.spec_from_file_location(
            f"amazon_order_status.{name}",
            integration_dir / f"{name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"amazon_order_status.{name}"] = module
        spec.loader.exec_module(module)

    return sys.modules["amazon_order_status.sensor"]


sensor = _load_sensor_module()


class SensorAttributeFilteringTest(unittest.TestCase):
    """Sensor attribute privacy coverage."""

    def test_status_sensors_follow_model_definitions(self):
        definitions = sys.modules[
            "amazon_order_status.models"
        ].STATUS_SENSOR_DEFINITIONS

        self.assertIn(
            ("partially_delivered", "Partially delivered", "Partially delivered"),
            definitions,
        )
        self.assertIn(
            ("ignored", "Ignored", "Ignored"),
            definitions,
        )
        self.assertEqual(
            list(definitions),
            [
                (
                    description.key,
                    description.name,
                    description.status,
                )
                for description in sensor.SENSORS
            ],
        )

    def test_sensitive_body_details_are_hidden_without_opt_in(self):
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
            "order_id": "306-2300519-2315556",
            "status": "Out for delivery",
            "subject": "In Zustellung: Example",
            "last_subject": "In Zustellung: Example",
            "item_title": "Example Product",
            "updated": "2026-06-19T13:33:08+00:00",
            "tracking_url": "https://www.amazon.de/gp/r.html?x=1",
            "delivery_estimate": "heute",
            "delivery_window": "15h - 19h",
            "carrier": "Amazon",
            "item_count": 1,
            "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
            "parser_debug": {"source": "body_details"},
            "history": [
                {
                    "status": "Out for delivery",
                    "subject": "In Zustellung: Example",
                    "updated": "2026-06-19T13:33:08+00:00",
                    "tracking_url": "https://www.amazon.de/gp/r.html?x=1",
                }
            ],
        }

        order = sensor._build_exposed_order(coordinator, data)

        self.assertEqual(
            {
                "status",
                "updated",
                "shipment_count",
                "shipments",
                "history",
                "manual",
                "ignored",
            },
            set(order),
        )
        self.assertEqual(
            {"status", "updated"},
            set(order["history"][0]),
        )
        self.assertEqual([], order["shipments"])

    def test_status_sensor_attributes_include_total_shipment_count(self):
        coordinator = SimpleNamespace(
            entry=SimpleNamespace(entry_id="entry-1"),
            data=[
                {
                    "order_id": "123-4567890-1234567",
                    "status": "Shipped",
                    "updated": "2026-06-26T10:00:00+00:00",
                    "shipment_count": 2,
                    "shipments": [{}, {}],
                    "history": [],
                    "manual": False,
                    "ignored": False,
                },
                {
                    "order_id": "123-4567890-7654321",
                    "status": "Shipped",
                    "updated": "2026-06-26T11:00:00+00:00",
                    "shipment_count": 1,
                    "shipments": [{}],
                    "history": [],
                    "manual": False,
                    "ignored": False,
                },
                {
                    "order_id": "123-4567890-0000000",
                    "status": "Delivered",
                    "updated": "2026-06-26T12:00:00+00:00",
                    "shipment_count": 4,
                    "shipments": [{}, {}, {}, {}],
                    "history": [],
                    "manual": False,
                    "ignored": False,
                },
            ],
            expose_order_id=False,
            expose_item_title=False,
            expose_tracking_url=False,
            expose_delivery_details=False,
            expose_carrier=False,
            expose_item_image=False,
            expose_parser_debug=False,
        )
        description = sensor.AmazonOrderSensorDescription(
            key="shipped",
            name="Shipped",
            status="Shipped",
        )
        status_sensor = sensor.AmazonOrderStatusSensor(coordinator, description)

        attributes = status_sensor.extra_state_attributes

        self.assertEqual(2, attributes["order_count"])
        self.assertEqual(3, attributes["shipment_count"])

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
                    "history": [
                        {
                            "status": "Delivered",
                            "subject": "Private title shipped",
                            "updated": "2026-06-26T12:00:00+00:00",
                            "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
                        }
                    ],
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
            {
                "status",
                "updated",
                "shipment_count",
                "shipments",
                "history",
                "manual",
                "ignored",
            },
            set(order),
        )
        self.assertEqual(
            {"status", "updated", "history", "manual", "ignored"},
            set(order["shipments"][0]),
        )
        self.assertEqual(
            {"status", "updated"},
            set(order["shipments"][0]["history"][0]),
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
                    "history": [
                        {
                            "status": "Delayed",
                            "subject": "Lieferung ist verspätet: Example",
                            "updated": "2026-06-26T12:00:00+00:00",
                            "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
                        }
                    ],
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
        self.assertEqual(
            "123-4567890-1234567:example",
            order["shipments"][0]["shipment_id"],
        )
        self.assertEqual("Example", order["shipments"][0]["item_title"])
        self.assertTrue(order["shipments"][0]["delivery_is_delayed"])
        self.assertIsNone(order["shipments"][0]["delivery_date_start"])
        self.assertEqual(
            "Lieferung ist verspätet: Example",
            order["shipments"][0]["history"][0]["subject"],
        )
        self.assertEqual(
            "https://www.amazon.de/gp/your-account/ship-track/example",
            order["shipments"][0]["history"][0]["tracking_url"],
        )

    def test_sensitive_body_details_are_visible_with_opt_in(self):
        coordinator = SimpleNamespace(
            expose_order_id=True,
            expose_item_title=True,
            expose_tracking_url=True,
            expose_delivery_details=True,
            expose_carrier=True,
            expose_item_image=True,
            expose_parser_debug=True,
        )
        data = {
            "order_id": "306-2300519-2315556",
            "status": "Delivered",
            "subject": "Zugestellt: 1 Artikel | Bestellung # 306-2300519-2315556",
            "last_subject": "Zugestellt: 1 Artikel | Bestellung # 306-2300519-2315556",
            "item_title": "Example Product",
            "updated": "2026-06-19T14:15:55+00:00",
            "tracking_url": "https://www.amazon.de/gp/r.html?x=1",
            "delivery_estimate": "heute",
            "delivered_at": "heute um 14:15",
            "carrier": "Amazon",
            "item_count": 1,
            "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
            "parser_debug": {"source": "body_details"},
            "history": [],
        }

        order = sensor._build_exposed_order(coordinator, data)

        self.assertEqual("306-2300519-2315556", order["order_id"])
        self.assertEqual("Example Product", order["item_title"])
        self.assertEqual("heute", order["delivery_estimate"])
        self.assertEqual("heute um 14:15", order["delivered_at"])
        self.assertEqual("Amazon", order["carrier"])
        self.assertEqual(1, order["item_count"])
        self.assertEqual(
            "https://m.media-amazon.com/images/I/example.jpg",
            order["item_image_url"],
        )
        self.assertEqual({"source": "body_details"}, order["parser_debug"])

    def test_opted_in_optional_attributes_are_none_when_missing(self):
        coordinator = SimpleNamespace(
            expose_order_id=False,
            expose_item_title=False,
            expose_tracking_url=True,
            expose_delivery_details=True,
            expose_carrier=True,
            expose_item_image=True,
            expose_parser_debug=False,
        )
        data = {
            "status": "Shipped",
            "updated": "2026-06-19T13:33:08+00:00",
            "history": [],
        }

        order = sensor._build_exposed_order(coordinator, data)

        for field in (
            "tracking_url",
            "delivery_estimate",
            "delivery_window",
            "delivered_at",
            "item_count",
            "carrier",
            "item_image_url",
        ):
            with self.subTest(field=field):
                self.assertIn(field, order)
                self.assertIsNone(order[field])


if __name__ == "__main__":
    unittest.main()
