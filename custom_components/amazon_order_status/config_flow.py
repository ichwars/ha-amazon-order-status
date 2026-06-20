"""Config flow for Amazon Order Status integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import imaplib
import socket
import voluptuous as vol

from .const import (
    CONF_EXPOSE_ITEM_TITLE,
    CONF_EXPOSE_ORDER_ID,
    CONF_EXPOSE_TRACKING_URL,
    CONF_IMAP_FOLDER,
    CONF_INITIAL_SCAN_DAYS,
    CONF_REQUIRE_AMAZON_SENDER,
    DOMAIN,
)
from .options_flow import AmazonOrderStatusOptionsFlow


def _select_folder_quoted(imap, folder: str) -> None:
    """Select IMAP mailbox using quoted name (IMAP4rev2-compatible)."""
    quoted = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
    imap._simple_command("SELECT", quoted.encode("utf-8"))


async def validate_imap_config(hass, host, port, username, password, folder=None):
    """Test connection to IMAP server."""

    def _validate():
        imap = None
        try:
            imap = imaplib.IMAP4_SSL(host, port)
            imap.login(username, password)
            folder_to_test = folder.strip() if folder and folder.strip() else "INBOX"
            _select_folder_quoted(imap, folder_to_test)
            return None
        except imaplib.IMAP4.error:
            return "invalid_auth"
        except (OSError, socket.gaierror):
            return "cannot_connect"
        finally:
            if imap is not None:
                try:
                    imap.logout()
                except imaplib.IMAP4.error:
                    pass

    return await hass.async_add_executor_job(_validate)


def _connection_fields(defaults: dict[str, Any] | None = None) -> dict[Any, Any]:
    """Return IMAP connection schema fields."""
    defaults = defaults or {}
    return {
        vol.Required(
            "email",
            default=defaults.get("email", ""),
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(
            "imap_server",
            default=defaults.get("imap_server", ""),
        ): TextSelector(),
        vol.Required(
            "username",
            default=defaults.get("username", ""),
        ): TextSelector(TextSelectorConfig(autocomplete="username")),
        vol.Required(
            "password",
            default=defaults.get("password", ""),
        ): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
        vol.Optional(
            "imap_port",
            default=defaults.get("imap_port", 993),
        ): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(
            CONF_IMAP_FOLDER,
            default=defaults.get(CONF_IMAP_FOLDER, ""),
        ): TextSelector(),
    }


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the IMAP connection schema."""
    return vol.Schema(_connection_fields(defaults))


def _setup_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the initial setup schema."""
    defaults = defaults or {}
    schema = _connection_fields(defaults)
    schema.update(
        {
            vol.Optional(
                "poll_interval",
                default=defaults.get("poll_interval", 5),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=1440, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_INITIAL_SCAN_DAYS,
                default=defaults.get(CONF_INITIAL_SCAN_DAYS, 14),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                "mark_as_read",
                default=defaults.get("mark_as_read", True),
            ): BooleanSelector(),
            vol.Optional(
                CONF_REQUIRE_AMAZON_SENDER,
                default=defaults.get(CONF_REQUIRE_AMAZON_SENDER, True),
            ): BooleanSelector(),
            vol.Optional(
                CONF_EXPOSE_ORDER_ID,
                default=defaults.get(CONF_EXPOSE_ORDER_ID, True),
            ): BooleanSelector(),
            vol.Optional(
                CONF_EXPOSE_ITEM_TITLE,
                default=defaults.get(CONF_EXPOSE_ITEM_TITLE, True),
            ): BooleanSelector(),
            vol.Optional(
                CONF_EXPOSE_TRACKING_URL,
                default=defaults.get(CONF_EXPOSE_TRACKING_URL, True),
            ): BooleanSelector(),
        }
    )
    return vol.Schema(schema)


class AmazonOrdersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amazon Orders."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step of the config flow."""
        errors = {}

        if user_input is not None:
            error = await validate_imap_config(
                self.hass,
                user_input["imap_server"],
                int(user_input.get("imap_port", 993)),
                user_input["username"],
                user_input["password"],
                user_input.get(CONF_IMAP_FOLDER),
            )

            if error is None:
                await self.async_set_unique_id(user_input["email"].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Amazon Orders",
                    data={
                        "email": user_input["email"],
                        "imap_server": user_input["imap_server"],
                        "username": user_input["username"],
                        "password": user_input["password"],
                        "imap_port": int(user_input.get("imap_port", 993)),
                    },
                    options={
                        "update_interval": int(user_input.get("poll_interval", 5)),
                        "delivered_retention_days": 30,
                        CONF_INITIAL_SCAN_DAYS: int(
                            user_input.get(CONF_INITIAL_SCAN_DAYS, 14)
                        ),
                        "mark_as_read": user_input.get("mark_as_read", True),
                        CONF_IMAP_FOLDER: user_input.get(CONF_IMAP_FOLDER, ""),
                        CONF_REQUIRE_AMAZON_SENDER: user_input.get(
                            CONF_REQUIRE_AMAZON_SENDER,
                            True,
                        ),
                        CONF_EXPOSE_ORDER_ID: user_input.get(CONF_EXPOSE_ORDER_ID, True),
                        CONF_EXPOSE_ITEM_TITLE: user_input.get(
                            CONF_EXPOSE_ITEM_TITLE,
                            True,
                        ),
                        CONF_EXPOSE_TRACKING_URL: user_input.get(
                            CONF_EXPOSE_TRACKING_URL,
                            True,
                        ),
                    },
                )

            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of IMAP credentials and endpoint."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            error = await validate_imap_config(
                self.hass,
                user_input["imap_server"],
                int(user_input.get("imap_port", 993)),
                user_input["username"],
                user_input["password"],
                entry.options.get(CONF_IMAP_FOLDER, ""),
            )
            if error is None:
                if entry.unique_id:
                    await self.async_set_unique_id(user_input["email"].lower())
                    self._abort_if_unique_id_mismatch()
                data_updates = dict(entry.data)
                data_updates.update(
                    {
                        "email": user_input["email"],
                        "imap_server": user_input["imap_server"],
                        "username": user_input["username"],
                        "password": user_input["password"],
                        "imap_port": int(user_input.get("imap_port", 993)),
                    }
                )
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data_updates,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler for this config entry."""
        return AmazonOrderStatusOptionsFlow(config_entry)
