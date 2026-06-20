"""Options flow for Amazon Order Status integration."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .const import (
    CONF_EXPOSE_CARRIER,
    CONF_EXPOSE_DELIVERY_DETAILS,
    CONF_EXPOSE_ITEM_TITLE,
    CONF_EXPOSE_ITEM_IMAGE,
    CONF_EXPOSE_ORDER_ID,
    CONF_EXPOSE_PARSER_DEBUG,
    CONF_EXPOSE_TRACKING_URL,
    CONF_IMAP_FOLDER,
    CONF_INITIAL_SCAN_DAYS,
    CONF_REQUIRE_AMAZON_SENDER,
)


class AmazonOrderStatusOptionsFlow(config_entries.OptionsFlow):
    """Handle an options flow for Amazon Order Status."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the initial step of the options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    "delivered_retention_days",
                    default=options.get("delivered_retention_days", 30),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=365, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    "update_interval",
                    default=options.get("update_interval", 5),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_INITIAL_SCAN_DAYS,
                    default=options.get(CONF_INITIAL_SCAN_DAYS, 14),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=365, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    "mark_as_read",
                    default=options.get("mark_as_read", True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_REQUIRE_AMAZON_SENDER,
                    default=options.get(CONF_REQUIRE_AMAZON_SENDER, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_ORDER_ID,
                    default=options.get(CONF_EXPOSE_ORDER_ID, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_ITEM_TITLE,
                    default=options.get(CONF_EXPOSE_ITEM_TITLE, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_TRACKING_URL,
                    default=options.get(CONF_EXPOSE_TRACKING_URL, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_DELIVERY_DETAILS,
                    default=options.get(CONF_EXPOSE_DELIVERY_DETAILS, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_CARRIER,
                    default=options.get(CONF_EXPOSE_CARRIER, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_ITEM_IMAGE,
                    default=options.get(CONF_EXPOSE_ITEM_IMAGE, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_EXPOSE_PARSER_DEBUG,
                    default=options.get(CONF_EXPOSE_PARSER_DEBUG, False),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_IMAP_FOLDER,
                    default=options.get(CONF_IMAP_FOLDER, ""),
                ): TextSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
