"""Options flow for Amazon Order Status integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .const import (
    CONF_DELIVERED_RETENTION_DAYS,
    CONF_EXPOSE_CARRIER,
    CONF_EXPOSE_DELIVERY_DETAILS,
    CONF_EXPOSE_ITEM_TITLE,
    CONF_EXPOSE_ITEM_IMAGE,
    CONF_EXPOSE_ORDER_ID,
    CONF_EXPOSE_PARSER_DEBUG,
    CONF_EXPOSE_TRACKING_URL,
    CONF_IMAP_FOLDER,
    CONF_INITIAL_SCAN_DAYS,
    CONF_MARK_AS_READ,
    CONF_REQUIRE_AMAZON_SENDER,
)

CONF_UPDATE_INTERVAL = "update_interval"
SECTION_ATTRIBUTES = "attributes"
SECTION_PROCESSING = "processing"
SECTION_SCAN = "scan"


def _number_box(min_value: int, max_value: int) -> NumberSelector:
    """Return a bounded numeric box selector."""
    return NumberSelector(
        NumberSelectorConfig(
            min=min_value,
            max=max_value,
            mode=NumberSelectorMode.BOX,
        )
    )


def _flatten_options_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten sectioned Home Assistant options input before storing it."""
    flattened: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in (SECTION_SCAN, SECTION_PROCESSING, SECTION_ATTRIBUTES) and isinstance(
            value,
            dict,
        ):
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


class AmazonOrderStatusOptionsFlow(config_entries.OptionsFlow):
    """Handle an options flow for Amazon Order Status."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the initial step of the options flow."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=_flatten_options_input(user_input),
            )

        options = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Required(SECTION_SCAN): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_DELIVERED_RETENTION_DAYS,
                                default=options.get(CONF_DELIVERED_RETENTION_DAYS, 30),
                            ): _number_box(1, 365),
                            vol.Required(
                                CONF_UPDATE_INTERVAL,
                                default=options.get(CONF_UPDATE_INTERVAL, 5),
                            ): _number_box(1, 1440),
                            vol.Required(
                                CONF_INITIAL_SCAN_DAYS,
                                default=options.get(CONF_INITIAL_SCAN_DAYS, 14),
                            ): _number_box(1, 365),
                            vol.Optional(
                                CONF_IMAP_FOLDER,
                                default=options.get(CONF_IMAP_FOLDER, ""),
                            ): TextSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_PROCESSING): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_MARK_AS_READ,
                                default=options.get(CONF_MARK_AS_READ, True),
                            ): BooleanSelector(),
                            vol.Required(
                                CONF_REQUIRE_AMAZON_SENDER,
                                default=options.get(CONF_REQUIRE_AMAZON_SENDER, True),
                            ): BooleanSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_ATTRIBUTES): section(
                    vol.Schema(
                        {
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
                                default=options.get(
                                    CONF_EXPOSE_DELIVERY_DETAILS,
                                    False,
                                ),
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
                        }
                    ),
                    {"collapsed": False},
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
