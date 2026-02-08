"""Amazon Order Status integration."""

from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AmazonOrdersCoordinator

PLATFORMS = ["sensor"]
DEFAULT_UPDATE_INTERVAL = 5  # minutes


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amazon Order Status from a config entry."""
    # Create the coordinator
    coordinator = AmazonOrdersCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Ensure DOMAIN dict exists
    hass.data.setdefault(DOMAIN, {})

    # Store coordinator under a fixed key for options_flow
    hass.data[DOMAIN]["coordinator"] = coordinator

    # Also store by entry_id for platform setup
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward entry setups (sensors)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove coordinator references
    if DOMAIN in hass.data:
        if "coordinator" in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop("coordinator")
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)

    return True
