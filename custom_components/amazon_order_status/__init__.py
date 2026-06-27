"""Amazon Order Status integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CLEAR_EXISTING,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS,
    ATTR_DELIVERED_AT,
    ATTR_ORDER_ID,
    ATTR_SHIPMENT_ID,
    ATTR_STATUS,
    DOMAIN,
    SERVICE_IGNORE_ORDER,
    SERVICE_MARK_DELIVERED,
    SERVICE_PURGE_ORDER,
    SERVICE_RESCAN,
    SERVICE_RESTORE_ORDER,
    SERVICE_SET_STATUS,
)
from .coordinator import AmazonOrdersCoordinator
from .models import ORDER_STATUSES

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

PURGE_ORDER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

RESCAN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DAYS, default=14): vol.All(
            vol.Coerce(int),
            vol.Range(min=1, max=365),
        ),
        vol.Optional(ATTR_CLEAR_EXISTING, default=False): cv.boolean,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

SET_STATUS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Required(ATTR_STATUS): vol.In(ORDER_STATUSES),
        vol.Optional(ATTR_SHIPMENT_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

MARK_DELIVERED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Optional(ATTR_DELIVERED_AT): cv.string,
        vol.Optional(ATTR_SHIPMENT_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

IGNORE_ORDER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Optional(ATTR_SHIPMENT_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

RESTORE_ORDER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): cv.string,
        vol.Optional(ATTR_SHIPMENT_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def _loaded_coordinators(
    hass: HomeAssistant,
    config_entry_id: str | None = None,
) -> list[AmazonOrdersCoordinator]:
    """Return loaded coordinators for a service call."""
    domain_data = hass.data.get(DOMAIN) or {}

    if config_entry_id:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None:
            raise ServiceValidationError(f"Config entry {config_entry_id} not found")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(f"Config entry {config_entry_id} not loaded")

        coordinator = domain_data.get(config_entry_id)
        if not isinstance(coordinator, AmazonOrdersCoordinator):
            raise ServiceValidationError(
                f"Amazon Order Status coordinator {config_entry_id} not loaded"
            )
        return [coordinator]

    return [
        coordinator
        for coordinator in domain_data.values()
        if isinstance(coordinator, AmazonOrdersCoordinator)
    ]


def _normalized_required_string(value: str, field_name: str) -> str:
    """Return a stripped required string value."""
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} must not be empty")
    return normalized


def _normalized_optional_string(value: str | None) -> str | None:
    """Return a stripped optional string value."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _has_matching_target(
    coordinator: AmazonOrdersCoordinator,
    order_id: str,
    shipment_id: str | None = None,
) -> bool:
    """Check whether a coordinator contains the requested order or shipment."""
    order = coordinator._orders.get(order_id)
    if order is None:
        return False
    if shipment_id is None:
        return True
    return coordinator._find_shipment(order, shipment_id) is not None


def _raise_target_not_found(order_id: str, shipment_id: str | None = None) -> None:
    """Raise a not-found error for a requested order or shipment."""
    if shipment_id is not None:
        raise HomeAssistantError(f"Shipment {shipment_id} for order {order_id} not found")
    raise HomeAssistantError(f"Order {order_id} not found")


async def _handle_purge_order(hass: HomeAssistant, call: ServiceCall) -> None:
    """Remove a specific order from tracking."""
    order_id = call.data[ATTR_ORDER_ID].strip()
    if not order_id:
        raise ServiceValidationError("order_id must not be empty")

    removed = False
    for coordinator in _loaded_coordinators(
        hass,
        call.data.get(ATTR_CONFIG_ENTRY_ID),
    ):
        if await coordinator.async_purge_order(order_id):
            removed = True

    if not removed:
        raise HomeAssistantError(f"Order {order_id} not found or already purged")


async def _handle_rescan(hass: HomeAssistant, call: ServiceCall) -> None:
    """Rescan Amazon order emails over a configurable lookback period."""
    days = call.data.get(ATTR_DAYS, 14)
    clear_existing = call.data.get(ATTR_CLEAR_EXISTING, False)
    coordinators = _loaded_coordinators(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))

    if not coordinators:
        raise ServiceValidationError("No Amazon Order Status coordinator is loaded")

    for coordinator in coordinators:
        count = await coordinator.async_rescan(days, clear_existing)
        _LOGGER.debug(
            "Rescan completed for %s with %d tracked orders",
            coordinator.entry.entry_id,
            count,
        )


async def _handle_set_status(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set one manual status for an order or shipment."""
    order_id = _normalized_required_string(call.data[ATTR_ORDER_ID], ATTR_ORDER_ID)
    shipment_id = _normalized_optional_string(call.data.get(ATTR_SHIPMENT_ID))
    status = call.data[ATTR_STATUS]

    matched = False
    for coordinator in _loaded_coordinators(
        hass,
        call.data.get(ATTR_CONFIG_ENTRY_ID),
    ):
        if not _has_matching_target(coordinator, order_id, shipment_id):
            continue
        matched = True
        await coordinator.async_set_status(order_id, status, shipment_id=shipment_id)

    if not matched:
        _raise_target_not_found(order_id, shipment_id)


async def _handle_mark_delivered(hass: HomeAssistant, call: ServiceCall) -> None:
    """Mark one order or shipment as delivered manually."""
    order_id = _normalized_required_string(call.data[ATTR_ORDER_ID], ATTR_ORDER_ID)
    shipment_id = _normalized_optional_string(call.data.get(ATTR_SHIPMENT_ID))
    delivered_at = _normalized_optional_string(call.data.get(ATTR_DELIVERED_AT))

    matched = False
    for coordinator in _loaded_coordinators(
        hass,
        call.data.get(ATTR_CONFIG_ENTRY_ID),
    ):
        if not _has_matching_target(coordinator, order_id, shipment_id):
            continue
        matched = True
        await coordinator.async_mark_delivered(
            order_id,
            shipment_id=shipment_id,
            delivered_at=delivered_at,
        )

    if not matched:
        _raise_target_not_found(order_id, shipment_id)


async def _handle_ignore_order(hass: HomeAssistant, call: ServiceCall) -> None:
    """Ignore one order or shipment."""
    order_id = _normalized_required_string(call.data[ATTR_ORDER_ID], ATTR_ORDER_ID)
    shipment_id = _normalized_optional_string(call.data.get(ATTR_SHIPMENT_ID))

    matched = False
    for coordinator in _loaded_coordinators(
        hass,
        call.data.get(ATTR_CONFIG_ENTRY_ID),
    ):
        if not _has_matching_target(coordinator, order_id, shipment_id):
            continue
        matched = True
        await coordinator.async_ignore_order(order_id, shipment_id=shipment_id)

    if not matched:
        _raise_target_not_found(order_id, shipment_id)


async def _handle_restore_order(hass: HomeAssistant, call: ServiceCall) -> None:
    """Restore one ignored order or shipment."""
    order_id = _normalized_required_string(call.data[ATTR_ORDER_ID], ATTR_ORDER_ID)
    shipment_id = _normalized_optional_string(call.data.get(ATTR_SHIPMENT_ID))

    matched = False
    for coordinator in _loaded_coordinators(
        hass,
        call.data.get(ATTR_CONFIG_ENTRY_ID),
    ):
        if not _has_matching_target(coordinator, order_id, shipment_id):
            continue
        matched = True
        await coordinator.async_restore_order(order_id, shipment_id=shipment_id)

    if not matched:
        _raise_target_not_found(order_id, shipment_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Amazon Order Status when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _make_purge_order_handler(hass: HomeAssistant):
    """Return an async service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_purge_order(hass, call)

    return handler


def _make_rescan_handler(hass: HomeAssistant):
    """Return an async rescan service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_rescan(hass, call)

    return handler


def _make_set_status_handler(hass: HomeAssistant):
    """Return an async set-status service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_set_status(hass, call)

    return handler


def _make_mark_delivered_handler(hass: HomeAssistant):
    """Return an async mark-delivered service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_mark_delivered(hass, call)

    return handler


def _make_ignore_order_handler(hass: HomeAssistant):
    """Return an async ignore-order service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_ignore_order(hass, call)

    return handler


def _make_restore_order_handler(hass: HomeAssistant):
    """Return an async restore-order service handler that closes over hass."""

    async def handler(call: ServiceCall) -> None:
        await _handle_restore_order(hass, call)

    return handler


SERVICE_REGISTRATIONS = (
    (SERVICE_PURGE_ORDER, _make_purge_order_handler, PURGE_ORDER_SCHEMA),
    (SERVICE_RESCAN, _make_rescan_handler, RESCAN_SCHEMA),
    (SERVICE_SET_STATUS, _make_set_status_handler, SET_STATUS_SCHEMA),
    (SERVICE_MARK_DELIVERED, _make_mark_delivered_handler, MARK_DELIVERED_SCHEMA),
    (SERVICE_IGNORE_ORDER, _make_ignore_order_handler, IGNORE_ORDER_SCHEMA),
    (SERVICE_RESTORE_ORDER, _make_restore_order_handler, RESTORE_ORDER_SCHEMA),
)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once per Home Assistant instance."""
    for service_name, handler_factory, schema in SERVICE_REGISTRATIONS:
        if hass.services.has_service(DOMAIN, service_name):
            continue
        hass.services.async_register(
            DOMAIN,
            service_name,
            handler_factory(hass),
            schema=schema,
        )


def _remove_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last entry unloads."""
    for service_name, _, _ in SERVICE_REGISTRATIONS:
        if hass.services.has_service(DOMAIN, service_name):
            hass.services.async_remove(DOMAIN, service_name)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amazon Order Status from a config entry."""
    coordinator = AmazonOrdersCoordinator(hass, entry)
    entry.runtime_data = coordinator

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await coordinator.async_config_entry_first_refresh()

    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            _remove_services(hass)

    return True
