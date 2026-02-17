"""Config flow for Amazon Order Status integration."""

from homeassistant import config_entries
import voluptuous as vol
import imaplib
import socket

from .const import DOMAIN, CONF_IMAP_FOLDER
from .options_flow import AmazonOrderStatusOptionsFlow


def _select_folder_quoted(imap, folder: str) -> None:
    """Select IMAP mailbox using quoted name (IMAP4rev2-compatible)."""
    quoted = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
    imap._simple_command("SELECT", quoted.encode("utf-8"))


async def validate_imap_config(hass, host, port, username, password, folder=None):
    """Test connection to IMAP server."""
    def _validate():
        try:
            imap = imaplib.IMAP4_SSL(host, port)
            imap.login(username, password)
            folder_to_test = folder.strip() if folder and folder.strip() else "INBOX"
            _select_folder_quoted(imap, folder_to_test)
            imap.logout()
            return None
        except imaplib.IMAP4.error:
            return "invalid_auth"
        except (OSError, socket.gaierror):
            return "cannot_connect"

    return await hass.async_add_executor_job(_validate)


class AmazonOrdersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amazon Orders."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step of the config flow."""
        errors = {}

        if user_input is not None:
            # Validate IMAP connection
            error = await validate_imap_config(
                self.hass,
                user_input["imap_server"],
                user_input.get("imap_port", 993),
                user_input["username"],
                user_input["password"],
                user_input.get(CONF_IMAP_FOLDER),
            )

            if error is None:
                # Create config entry with initial options including mark_as_read
                return self.async_create_entry(
                    title="Amazon Orders",
                    data={
                        "email": user_input["email"],
                        "imap_server": user_input["imap_server"],
                        "username": user_input["username"],
                        "password": user_input["password"],
                        "imap_port": user_input.get("imap_port", 993),
                    },
                    options={
                        "update_interval": user_input.get("poll_interval", 5),
                        "delivered_retention_days": 30,
                        "mark_as_read": user_input.get("mark_as_read", True),
                        CONF_IMAP_FOLDER: user_input.get(CONF_IMAP_FOLDER, ""),
                    },
                )

            errors["base"] = error

        # Show the form with mark_as_read option
        schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("imap_server"): str,
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Optional("imap_port", default=993): int,
                vol.Optional("poll_interval", default=5): int,
                vol.Optional("mark_as_read", default=True): bool,
                vol.Optional(CONF_IMAP_FOLDER, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler for this config entry."""
        return AmazonOrderStatusOptionsFlow(config_entry)
