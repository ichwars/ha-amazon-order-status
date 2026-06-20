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
    ATTR_ORDER_ID,
    DOMAIN,
    SERVICE_PURGE_ORDER,
    SERVICE_RESCAN,
)
from .coordinator import AmazonOrdersCoordinator

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amazon Order Status from a config entry."""
    coordinator = AmazonOrdersCoordinator(hass, entry)
    entry.runtime_data = coordinator

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await coordinator.async_config_entry_first_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_PURGE_ORDER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_PURGE_ORDER,
            _make_purge_order_handler(hass),
            schema=PURGE_ORDER_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_RESCAN):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESCAN,
            _make_rescan_handler(hass),
            schema=RESCAN_SCHEMA,
        )

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
            if hass.services.has_service(DOMAIN, SERVICE_PURGE_ORDER):
                hass.services.async_remove(DOMAIN, SERVICE_PURGE_ORDER)
            if hass.services.has_service(DOMAIN, SERVICE_RESCAN):
                hass.services.async_remove(DOMAIN, SERVICE_RESCAN)

    return True
