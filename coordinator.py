"""Amazon Orders Data Coordinator."""

from __future__ import annotations

import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
import email.utils
from email import message_from_bytes
from email.header import decode_header
from typing import Dict

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
import html
from bs4 import BeautifulSoup

from .const import CONF_MARK_AS_READ

_LOGGER = logging.getLogger(__name__)
LAST_CHECK_KEY = "last_check"
STORAGE_VERSION = 1
STORAGE_KEY = "amazon_order_status"
ORDERS_KEY = "orders"

ORDER_REGEX = re.compile(r"Order\s*#\s*([0-9\-]{10,})", re.IGNORECASE)

STATUS_MAP = {
    "ordered": "Ordered",
    "shipped": "Shipped",
    "out for delivery": "Out for delivery",
    "delivered": "Delivered",
}


class AmazonOrdersCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch and track Amazon orders via email."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._orders: Dict[str, dict] = {}
        self.delivered_retention_days = entry.options.get("delivered_retention_days", 7)
        self._mark_as_read = entry.options.get(CONF_MARK_AS_READ, False)

        # Determine update interval from options or config entry, default 5 min
        interval_minutes = entry.options.get(
            "update_interval", entry.data.get("update_interval", 5)
        )

        super().__init__(
            hass,
            _LOGGER,
            name="Amazon Order Status",
            update_interval=timedelta(minutes=interval_minutes),
        )

    """ Timestamp storage/retrieval functions to reduce email check time """
    async def async_load_last_check(self) -> datetime | None:
        stored = await self._store.async_load()
        if stored and LAST_CHECK_KEY in stored:
            return datetime.fromisoformat(stored[LAST_CHECK_KEY])
        return None

    async def async_load_stored_orders(self) -> None:
        """Load persisted orders from storage."""
        stored = await self._store.async_load()
        if stored:
            self._orders = stored.get(ORDERS_KEY, {})
            _LOGGER.debug("Loaded %d stored Amazon orders", len(self._orders))
        else:
            self._orders = {}
            _LOGGER.debug("No stored Amazon orders found")

    async def async_save_state(self, last_check: datetime) -> None:
        await self._store.async_save(
            {
                LAST_CHECK_KEY: last_check.isoformat(),
                ORDERS_KEY: self._orders,
            }
        )

    async def _async_update_data(self):
        _LOGGER.debug("Coordinator update triggered at %s", datetime.now(timezone.utc))

        if not self._orders:
            await self.async_load_stored_orders()

        last_check = await self.async_load_last_check()
        now = datetime.now(timezone.utc)

        await self.hass.async_add_executor_job(
            self._fetch_and_parse_emails,
            last_check,
            now,
        )

        # Purge old delivered orders
        self._purge_old_delivered_orders(now)

        await self.async_save_state(now)

        return list(self._orders.values())

    @callback
    def async_update_interval(self, minutes: int):
        """Dynamically update the coordinator's refresh interval."""
        self.update_interval = timedelta(minutes=minutes)
        _LOGGER.debug("Coordinator update interval set to %d minutes", minutes)
        self.hass.async_create_task(self.async_refresh())

    @callback
    def async_set_retention_days(self, days: int):
        """Update delivered retention days and immediately purge old delivered orders."""
        self.delivered_retention_days = days
        _LOGGER.debug("Delivered retention days updated to %d", days)
        self._purge_old_delivered_orders(datetime.now(timezone.utc))

    @callback
    def async_set_mark_as_read(self, mark_as_read: bool):
        """Enable or disable marking emails as read."""
        self._mark_as_read = mark_as_read
        _LOGGER.debug("Mark as read option updated: %s", mark_as_read)

        # Update the config entry safely
        new_options = dict(self.entry.options)
        new_options[CONF_MARK_AS_READ] = mark_as_read
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    @callback
    def _purge_old_delivered_orders(self, now: datetime):
        """Remove delivered orders older than retention period."""
        if not self._orders:
            return

        retention_cutoff = now - timedelta(days=self.delivered_retention_days)
        to_remove = [
            order_id
            for order_id, order in self._orders.items()
            if order.get("status") == "Delivered"
            and datetime.fromisoformat(order.get("updated")) < retention_cutoff
        ]

        for order_id in to_remove:
            _LOGGER.debug(
                "Purging delivered order %s (older than %d days)",
                order_id,
                self.delivered_retention_days,
            )
            self._orders.pop(order_id, None)

    def _fetch_and_parse_emails(self, last_check: datetime | None, now: datetime):
        """Connect to IMAP and parse Amazon emails."""
        email_addr = self.entry.data["email"]
        password = self.entry.data["password"]
        imap_server = self.entry.data["imap_server"]
        mark_as_read = self._mark_as_read

        _LOGGER.debug("Connecting to IMAP server %s as %s", imap_server, email_addr)

        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(email_addr, password)
        mail.select("INBOX")

        if last_check:
            since = last_check
            _LOGGER.debug("Checking emails since last run: %s", since)
        else:
            since = now - timedelta(days=14)
            _LOGGER.debug("First run: checking last 14 days")

        since_date = since.strftime("%d-%b-%Y")
        typ, data = mail.search(None, f'(SINCE "{since_date}")')

        if typ != "OK":
            _LOGGER.error("IMAP search failed")
            mail.logout()
            return

        email_nums = data[0].split()
        _LOGGER.debug("Found %d emails since %s", len(email_nums), since_date)

        for num in email_nums:
            typ, msg_data = mail.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                _LOGGER.warning("Failed to fetch email %s", num)
                continue

            msg = message_from_bytes(msg_data[0][1])
            msg_date = msg.get("Date")
            if not msg_date:
                _LOGGER.debug("Email %s has no Date header", num)
                continue

            msg_datetime = email.utils.parsedate_to_datetime(msg_date)
            if msg_datetime.tzinfo is None:
                msg_datetime = msg_datetime.replace(tzinfo=timezone.utc)

            if msg_datetime <= since:
                continue

            subject = self._decode_header(msg.get("Subject", ""))
            subject_lower = subject.lower()

            status = self._status_from_subject(subject_lower)
            if not status:
                continue

            body_text = self._extract_text(msg)
            html_body = self._extract_html(msg)

            order_ids = ORDER_REGEX.findall(body_text)
            if not order_ids:
                _LOGGER.debug("No order numbers found in email: %s", subject)
                continue  # <-- skip processing this email entirely

            tracking_url = self._extract_tracking_url(html_body) if html_body else None

            for order_id in order_ids:
                self._orders[order_id] = {
                    "status": status,
                    "subject": subject,
                    "updated": msg_datetime.isoformat(),
                    "tracking_url": tracking_url,
                }

                _LOGGER.debug(
                    "Order %s → %s (%s) [tracking: %s]",
                    order_id,
                    status,
                    subject,
                    tracking_url,
                )

            if mark_as_read:
                _LOGGER.debug("Marking email %s as read", num)
                mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()

    def _status_from_subject(self, subject: str) -> str | None:
        """Determine order status from email subject."""
        for key, value in STATUS_MAP.items():
            if key in subject:
                return value
        return None

    def _decode_header(self, value: str) -> str:
        """Decode email headers safely."""
        parts = decode_header(value)
        decoded = ""
        for text, encoding in parts:
            if isinstance(text, bytes):
                decoded += text.decode(encoding or "utf-8", errors="ignore")
            else:
                decoded += text
        return decoded

    def _extract_text(self, msg) -> str:
        """Extract flattened text from email."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(errors="ignore")
        return ""

    def _extract_html(self, msg) -> str:
        """Extract HTML body from email."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        else:
            if msg.get_content_type() == "text/html":
                payload = msg.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="ignore")
        return ""

    def _extract_tracking_url(self, html_body: str) -> str | None:
        """Extract Amazon tracking URL or order link from email HTML."""
        soup = BeautifulSoup(html_body, "html.parser")

        for link in soup.find_all("a", href=True):
            text = link.get_text(" ", strip=True).lower()
            href = html.unescape(link["href"])

            # Case 1: Tracking links
            if "track package" in text or "progress-tracker" in href:
                match = re.search(
                    r"https://www\.amazon\.com/progress-tracker/[^&\"]+",
                    href,
                )
                if match:
                    return match.group(0)
                return href

            # Case 2: Order management links
            if "your-orders" in href and ("view" in text or "edit order" in text):
                return href

        return None
