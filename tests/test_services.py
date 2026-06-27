"""Runtime tests for Amazon Order Status service handling."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import types
import unittest

try:
    import voluptuous as vol
except ModuleNotFoundError:  # pragma: no cover - exercised only in the stripped test env
    _MISSING = object()

    class Invalid(Exception):
        pass

    class _Marker:
        def __init__(self, key: str, *, default=_MISSING, required: bool) -> None:
            self.key = key
            self.default = default
            self.required = required

    class Required(_Marker):
        def __init__(self, key: str) -> None:
            super().__init__(key, required=True)

    class Optional(_Marker):
        def __init__(self, key: str, default=_MISSING) -> None:
            super().__init__(key, default=default, required=False)

    def Coerce(factory):
        def validator(value):
            try:
                return factory(value)
            except Exception as err:  # noqa: BLE001
                raise Invalid(str(err)) from err

        return validator

    def Range(*, min=None, max=None):
        def validator(value):
            if min is not None and value < min:
                raise Invalid(f"{value} is less than minimum {min}")
            if max is not None and value > max:
                raise Invalid(f"{value} is greater than maximum {max}")
            return value

        return validator

    def In(options):
        def validator(value):
            if value not in options:
                raise Invalid(f"{value!r} is not an allowed value")
            return value

        return validator

    def All(*validators):
        def validator(value):
            current = value
            for item in validators:
                current = item(current)
            return current

        return validator

    class Schema:
        def __init__(self, mapping: dict) -> None:
            self._mapping = mapping

        def __call__(self, data: dict) -> dict:
            validated: dict = {}
            for schema_key, validator in self._mapping.items():
                marker = (
                    schema_key
                    if isinstance(schema_key, _Marker)
                    else Required(schema_key)
                )
                if marker.key in data:
                    validated[marker.key] = validator(data[marker.key])
                    continue
                if marker.required:
                    raise Invalid(f"required key not provided: {marker.key}")
                if marker.default is not _MISSING:
                    validated[marker.key] = validator(marker.default)
            return validated

    vol = types.ModuleType("voluptuous")
    vol.Invalid = Invalid
    vol.MultipleInvalid = Invalid
    vol.Required = Required
    vol.Optional = Optional
    vol.Coerce = Coerce
    vol.Range = Range
    vol.In = In
    vol.All = All
    vol.Schema = Schema
    sys.modules["voluptuous"] = vol


def _load_integration_module():
    """Load the integration package with minimal Home Assistant stubs."""
    for name in list(sys.modules):
        if name == "amazon_order_status" or name.startswith("amazon_order_status."):
            sys.modules.pop(name)

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        pass

    class ConfigEntryState:
        LOADED = object()

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigEntryState = ConfigEntryState

    const = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"

    const.Platform = Platform

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    class ServiceCall:
        def __init__(self, data: dict):
            self.data = data

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ServiceValidationError(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ServiceValidationError = ServiceValidationError

    helpers = types.ModuleType("homeassistant.helpers")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    config_validation.string = vol.Coerce(str)
    config_validation.boolean = vol.Coerce(bool)
    helpers.config_validation = config_validation

    coordinator_module = types.ModuleType("amazon_order_status.coordinator")

    class AmazonOrdersCoordinator:
        def __init__(self, entry_id: str, orders: dict | None = None):
            self.entry = SimpleNamespace(entry_id=entry_id)
            self._orders = orders or {}
            self.set_status_calls: list[tuple[str, str, str | None]] = []
            self.mark_delivered_calls: list[tuple[str, str | None, str | None]] = []
            self.ignore_order_calls: list[tuple[str, str | None]] = []
            self.restore_order_calls: list[tuple[str, str | None]] = []

        def _find_shipment(
            self,
            order: dict,
            shipment_id: str,
        ) -> dict | None:
            for shipment in order.get("shipments", []):
                if shipment.get("shipment_id") == shipment_id:
                    return shipment
            return None

        async def async_set_status(
            self,
            order_id: str,
            status: str,
            shipment_id: str | None = None,
        ) -> bool:
            self.set_status_calls.append((order_id, status, shipment_id))
            return True

        async def async_mark_delivered(
            self,
            order_id: str,
            shipment_id: str | None = None,
            delivered_at: str | None = None,
        ) -> bool:
            self.mark_delivered_calls.append((order_id, shipment_id, delivered_at))
            return True

        async def async_ignore_order(
            self,
            order_id: str,
            shipment_id: str | None = None,
        ) -> bool:
            self.ignore_order_calls.append((order_id, shipment_id))
            return True

        async def async_restore_order(
            self,
            order_id: str,
            shipment_id: str | None = None,
        ) -> bool:
            self.restore_order_calls.append((order_id, shipment_id))
            return True

    coordinator_module.AmazonOrdersCoordinator = AmazonOrdersCoordinator

    sys.modules.update(
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.exceptions": exceptions,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.config_validation": config_validation,
            "amazon_order_status.coordinator": coordinator_module,
        }
    )

    integration_dir = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "amazon_order_status"
    )
    spec = importlib.util.spec_from_file_location(
        "amazon_order_status",
        integration_dir / "__init__.py",
        submodule_search_locations=[str(integration_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["amazon_order_status"] = module
    spec.loader.exec_module(module)
    return module, AmazonOrdersCoordinator, ConfigEntryState, HomeAssistantError


module, FakeCoordinator, ConfigEntryState, HomeAssistantError = _load_integration_module()


class FakeServiceRegistry:
    """Small in-memory service registry for handler tests."""

    def __init__(self) -> None:
        self._services: dict[tuple[str, str], tuple[object, object]] = {}

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._services

    def async_register(
        self,
        domain: str,
        service: str,
        handler,
        *,
        schema=None,
    ) -> None:
        self._services[(domain, service)] = (handler, schema)

    def async_remove(self, domain: str, service: str) -> None:
        self._services.pop((domain, service), None)

    async def async_call(self, domain: str, service: str, data: dict):
        handler, schema = self._services[(domain, service)]
        validated = schema(dict(data)) if schema is not None else dict(data)
        await handler(module.ServiceCall(validated))
        return validated

    def names_for_domain(self, domain: str) -> set[str]:
        return {
            service_name
            for registered_domain, service_name in self._services
            if registered_domain == domain
        }


class FakeConfigEntries:
    """Fake config entry manager with lookup support."""

    def __init__(self, entries: list[SimpleNamespace]) -> None:
        self._entries = {entry.entry_id: entry for entry in entries}

    def async_get_entry(self, entry_id: str) -> SimpleNamespace | None:
        return self._entries.get(entry_id)


class FakeHass:
    """Minimal Home Assistant stub for service registration and calls."""

    def __init__(self, coordinators: list[FakeCoordinator]) -> None:
        self.services = FakeServiceRegistry()
        self.config_entries = FakeConfigEntries(
            [
                SimpleNamespace(
                    entry_id=coordinator.entry.entry_id,
                    state=ConfigEntryState.LOADED,
                )
                for coordinator in coordinators
            ]
        )
        self.data = {
            module.DOMAIN: {
                coordinator.entry.entry_id: coordinator for coordinator in coordinators
            }
        }


def _order(order_id: str, *shipment_ids: str) -> dict:
    return {
        "order_id": order_id,
        "shipments": [
            {"shipment_id": shipment_id}
            for shipment_id in shipment_ids
        ],
    }


class ServiceRuntimeTest(unittest.TestCase):
    """Exercise the real service layer through a fake Home Assistant runtime."""

    def _make_hass(self, *coordinators: FakeCoordinator) -> FakeHass:
        hass = FakeHass(list(coordinators))
        module._register_services(hass)
        return hass

    def test_registers_and_removes_all_services(self):
        coordinator = FakeCoordinator("entry-1", {})
        hass = self._make_hass(coordinator)

        self.assertEqual(
            {
                module.SERVICE_PURGE_ORDER,
                module.SERVICE_RESCAN,
                module.SERVICE_SET_STATUS,
                module.SERVICE_MARK_DELIVERED,
                module.SERVICE_IGNORE_ORDER,
                module.SERVICE_RESTORE_ORDER,
            },
            hass.services.names_for_domain(module.DOMAIN),
        )

        module._register_services(hass)
        self.assertEqual(6, len(hass.services.names_for_domain(module.DOMAIN)))

        module._remove_services(hass)
        self.assertEqual(set(), hass.services.names_for_domain(module.DOMAIN))

    def test_set_status_schema_rejects_unknown_status(self):
        coordinator = FakeCoordinator(
            "entry-1",
            {"123-4567890-1234567": _order("123-4567890-1234567")},
        )
        hass = self._make_hass(coordinator)

        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_SET_STATUS,
                {
                    module.ATTR_ORDER_ID: "123-4567890-1234567",
                    module.ATTR_STATUS: "Delivered",
                },
            )
        )
        self.assertEqual(
            [("123-4567890-1234567", "Delivered", None)],
            coordinator.set_status_calls,
        )

        with self.assertRaises(vol.Invalid):
            asyncio.run(
                hass.services.async_call(
                    module.DOMAIN,
                    module.SERVICE_SET_STATUS,
                    {
                        module.ATTR_ORDER_ID: "123-4567890-1234567",
                        module.ATTR_STATUS: "Front door",
                    },
                )
            )

    def test_set_status_rejects_rollup_only_status_for_target_shipment(self):
        order_id = "123-4567890-1234567"
        shipment_id = f"{order_id}:default"
        coordinator = FakeCoordinator(
            "entry-1",
            {order_id: _order(order_id, shipment_id)},
        )
        hass = self._make_hass(coordinator)

        with self.assertRaises(module.ServiceValidationError):
            asyncio.run(
                hass.services.async_call(
                    module.DOMAIN,
                    module.SERVICE_SET_STATUS,
                    {
                        module.ATTR_ORDER_ID: order_id,
                        module.ATTR_SHIPMENT_ID: shipment_id,
                        module.ATTR_STATUS: "Partially delivered",
                    },
                )
            )

        self.assertEqual([], coordinator.set_status_calls)

    def test_mark_delivered_accepts_iso_values_and_blank_and_rejects_free_text(self):
        order_id = "123-4567890-1234567"
        shipment_id = f"{order_id}:default"
        coordinator = FakeCoordinator(
            "entry-1",
            {order_id: _order(order_id, shipment_id)},
        )
        hass = self._make_hass(coordinator)

        for delivered_at in (
            "2026-06-27",
            "2026-06-27T18:30:00+02:00",
            "2026-06-27 18:30",
        ):
            with self.subTest(delivered_at=delivered_at):
                asyncio.run(
                    hass.services.async_call(
                        module.DOMAIN,
                        module.SERVICE_MARK_DELIVERED,
                        {
                            module.ATTR_ORDER_ID: order_id,
                            module.ATTR_SHIPMENT_ID: shipment_id,
                            module.ATTR_DELIVERED_AT: delivered_at,
                        },
                    )
                )
                self.assertEqual(
                    (order_id, shipment_id, delivered_at),
                    coordinator.mark_delivered_calls[-1],
                )

        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_MARK_DELIVERED,
                {
                    module.ATTR_ORDER_ID: order_id,
                    module.ATTR_SHIPMENT_ID: shipment_id,
                    module.ATTR_DELIVERED_AT: "   ",
                },
            )
        )
        self.assertEqual(
            (order_id, shipment_id, None),
            coordinator.mark_delivered_calls[-1],
        )

        for delivered_at in (
            "Front door",
            "https://example.com/track",
            "123-4567890-1234567",
            "1Z999AA10123456784",
        ):
            with self.subTest(delivered_at=delivered_at):
                with self.assertRaises(vol.Invalid):
                    asyncio.run(
                        hass.services.async_call(
                            module.DOMAIN,
                            module.SERVICE_MARK_DELIVERED,
                            {
                                module.ATTR_ORDER_ID: order_id,
                                module.ATTR_SHIPMENT_ID: shipment_id,
                                module.ATTR_DELIVERED_AT: delivered_at,
                            },
                        )
                    )

    def test_manual_service_handlers_call_matching_coordinator_methods(self):
        order_id = "123-4567890-1234567"
        shipment_id = f"{order_id}:default"
        coordinator = FakeCoordinator(
            "entry-1",
            {order_id: _order(order_id, shipment_id)},
        )
        hass = self._make_hass(coordinator)

        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_SET_STATUS,
                {
                    module.ATTR_ORDER_ID: order_id,
                    module.ATTR_SHIPMENT_ID: shipment_id,
                    module.ATTR_STATUS: "Delivered",
                },
            )
        )
        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_MARK_DELIVERED,
                {
                    module.ATTR_ORDER_ID: order_id,
                    module.ATTR_DELIVERED_AT: "2026-06-27",
                },
            )
        )
        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_IGNORE_ORDER,
                {module.ATTR_ORDER_ID: order_id},
            )
        )
        asyncio.run(
            hass.services.async_call(
                module.DOMAIN,
                module.SERVICE_RESTORE_ORDER,
                {
                    module.ATTR_ORDER_ID: order_id,
                    module.ATTR_SHIPMENT_ID: shipment_id,
                },
            )
        )

        self.assertEqual(
            [("123-4567890-1234567", "Delivered", shipment_id)],
            coordinator.set_status_calls,
        )
        self.assertEqual(
            [("123-4567890-1234567", None, "2026-06-27")],
            coordinator.mark_delivered_calls,
        )
        self.assertEqual(
            [("123-4567890-1234567", None)],
            coordinator.ignore_order_calls,
        )
        self.assertEqual(
            [("123-4567890-1234567", shipment_id)],
            coordinator.restore_order_calls,
        )

    def test_manual_services_raise_when_order_is_missing(self):
        hass = self._make_hass(FakeCoordinator("entry-1", {}))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(
                hass.services.async_call(
                    module.DOMAIN,
                    module.SERVICE_IGNORE_ORDER,
                    {module.ATTR_ORDER_ID: "missing-order"},
                )
            )

    def test_manual_services_raise_when_shipment_is_missing(self):
        order_id = "123-4567890-1234567"
        hass = self._make_hass(
            FakeCoordinator("entry-1", {order_id: _order(order_id, f"{order_id}:default")})
        )

        with self.assertRaises(HomeAssistantError):
            asyncio.run(
                hass.services.async_call(
                    module.DOMAIN,
                    module.SERVICE_RESTORE_ORDER,
                    {
                        module.ATTR_ORDER_ID: order_id,
                        module.ATTR_SHIPMENT_ID: f"{order_id}:missing",
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
