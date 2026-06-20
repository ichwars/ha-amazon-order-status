"""Amazon Orders Data Coordinator."""

from __future__ import annotations

import imaplib
import logging
import re
import socket
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import email.utils
from email import message_from_bytes
from email.header import decode_header
from urllib.parse import urlparse
from typing import Dict

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
import html
from bs4 import BeautifulSoup

from .const import (
    CONF_EXPOSE_ITEM_TITLE,
    CONF_EXPOSE_ORDER_ID,
    CONF_EXPOSE_TRACKING_URL,
    CONF_IMAP_FOLDER,
    CONF_INITIAL_SCAN_DAYS,
    CONF_MARK_AS_READ,
    CONF_REQUIRE_AMAZON_SENDER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    """Result of one IMAP scan."""

    success: bool
    processed_until: datetime
    error: str | None = None


def _parse_internaldate(internaldate_str: str) -> datetime | None:
    """Parse IMAP INTERNALDATE string to timezone-aware UTC datetime."""
    try:
        # Format: "08-Feb-2025 18:30:00 +0000" or "08-Feb-2025 10:30:00 -0800"
        internaldate_str = internaldate_str.strip()
        if len(internaldate_str) < 26:
            return None
        dt = datetime.strptime(internaldate_str[:20], "%d-%b-%Y %H:%M:%S")
        tz_str = internaldate_str[20:].strip()
        if not tz_str:
            return dt.replace(tzinfo=timezone.utc)
        sign = -1 if tz_str[0] == "-" else 1
        hours = int(tz_str[1:3])
        mins = int(tz_str[3:5]) if len(tz_str) >= 5 else 0
        tz = timezone(timedelta(minutes=sign * (hours * 60 + mins)))
        return dt.replace(tzinfo=tz).astimezone(timezone.utc)
    except (ValueError, IndexError):
        return None


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
LAST_CHECK_KEY = "last_check"
STORAGE_VERSION = 1
STORAGE_KEY = "amazon_order_status"
ORDERS_KEY = "orders"

ORDER_ID_REGEXES = (
    # Standard Amazon order IDs are distinctive enough to detect anywhere,
    # including German mails where the label can vary or be omitted in links.
    re.compile(r"\b([0-9]{3}-[0-9]{7}-[0-9]{7})\b"),
    re.compile(
        r"(?:Order|Purchase|Bestellung|Bestellnummer|"
        r"Bestell(?:-|\s*)Nr\.?|Bestell(?:-|\s*)ID)"
        r"\s*(?:#|number|ID|No\.?|Nr\.?)?\s*[:#]?\s*"
        r"([0-9][0-9\-]{9,})",
        re.IGNORECASE,
    ),
)

AMAZON_DOMAIN_PATTERN = re.compile(
    r"(^|\.)amazon\."
    r"(com|de|co\.uk|fr|it|es|nl|se|pl|com\.be|com\.mx|ca|co\.jp|"
    r"com\.au|com\.tr|ae|sa|sg|in|com\.br)$",
    re.IGNORECASE,
)

# IMAP INTERNALDATE format: "08-Feb-2025 18:30:00 +0000"
INTERNALDATE_RE = re.compile(r'INTERNALDATE\s+"([^"]+)"', re.IGNORECASE)

# English month abbreviations for IMAP date (RFC 3501); avoid locale-dependent strftime
_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _imap_date_str(dt: datetime) -> str:
    """Return date in IMAP format dd-Mon-yyyy (English month) for SEARCH SINCE."""
    return f"{dt.day:02d}-{_IMAP_MONTHS[dt.month - 1]}-{dt.year}"


def _extract_order_ids_from_text(*texts: str) -> list[str]:
    """Extract Amazon order IDs from plain text, HTML, and embedded links."""
    order_ids: list[str] = []
    for text in texts:
        if not text:
            continue
        for regex in ORDER_ID_REGEXES:
            for order_id in regex.findall(text):
                if order_id not in order_ids:
                    order_ids.append(order_id)
    return order_ids


def _domain_is_amazon(domain: str | None) -> bool:
    """Return True if an email or URL host belongs to an Amazon domain."""
    if not domain:
        return False
    return AMAZON_DOMAIN_PATTERN.search(domain.lower().strip(".")) is not None


def _message_from_amazon(msg) -> bool:
    """Return True when sender headers point at an Amazon domain."""
    addresses: list[str] = []
    for header in ("From", "Sender", "Reply-To", "Return-Path"):
        value = msg.get(header)
        if value:
            addresses.extend(address for _name, address in email.utils.getaddresses([value]))

    for address in addresses:
        if "@" not in address:
            continue
        domain = address.rsplit("@", 1)[-1]
        if _domain_is_amazon(domain):
            return True
    return False


def _safe_amazon_url(href: str | None) -> str | None:
    """Return href only when it is an HTTPS Amazon URL."""
    if not href:
        return None

    parsed = urlparse(href)
    if parsed.scheme != "https" or not _domain_is_amazon(parsed.hostname):
        return None
    return href


def _extract_item_title(subject: str) -> str | None:
    """Extract a human-readable item title from Amazon status subjects."""
    match = re.search(r"^[^:]+:\s*[„\"“]?(.+?)[”\"“]?$", subject)
    if not match:
        return None

    item = match.group(1)
    item = re.split(r"\s+-\s+amazon\.", item, maxsplit=1, flags=re.IGNORECASE)[0]
    item_lower = item.lower()
    if "bestellung #" in item_lower or "artikel |" in item_lower:
        return None

    item = item.strip(" „\"“”")
    return item or None


def _normalize_item_key(item_title: str | None) -> str | None:
    """Normalize an item title for matching related Amazon status emails."""
    if not item_title:
        return None

    item = re.sub(r"\.\.\.|…", " ", item_title.lower())
    item = re.sub(r"[^a-z0-9äöüß]+", " ", item)
    item = re.sub(r"\s+", " ", item).strip()
    return item or None


def _subject_item_key(subject: str) -> str | None:
    """Return a normalized item key from status subjects like 'Versendet: "Item"'."""
    return _normalize_item_key(_extract_item_title(subject))


def _order_item_key(order: dict) -> str | None:
    """Return the best available normalized item key for a stored order."""
    return _normalize_item_key(order.get("item_title")) or _subject_item_key(
        order.get("subject", "")
    )


def _history_entry(
    status: str,
    subject: str,
    updated: str,
    tracking_url: str | None,
) -> dict:
    """Build a compact history event for a status email."""
    return {
        "status": status,
        "subject": subject,
        "updated": updated,
        "tracking_url": tracking_url,
    }


def _append_history(existing: dict | None, event: dict) -> list[dict]:
    """Append a status event unless it is already present."""
    history = list((existing or {}).get("history") or [])
    if not any(
        item.get("status") == event["status"]
        and item.get("updated") == event["updated"]
        and item.get("subject") == event["subject"]
        for item in history
    ):
        history.append(event)
    return history[-20:]


def _new_scan_stats(folder: str, since: datetime, now: datetime) -> dict:
    """Return a fresh scan diagnostics structure."""
    return {
        "started": now.isoformat(),
        "since": since.isoformat(),
        "imap_folder": folder,
        "email_count": 0,
        "fetched_count": 0,
        "recognized_count": 0,
        "updated_count": 0,
        "matched_by_subject_count": 0,
        "skipped_before_last_check": 0,
        "skipped_no_date": 0,
        "skipped_sender": 0,
        "skipped_no_status": 0,
        "skipped_no_order_id": 0,
        "skipped_ambiguous_subject_match": 0,
        "skipped_status_regression": 0,
        "skipped_older_duplicate": 0,
        "failed_fetch_count": 0,
        "error": None,
    }


LANGUAGE_PROFILES = {
    "en": {
        "Ordered": (
            r"\bsuccessfully placed your order\b",
            r"\bwe've received your order\b",
            r"\bpreparing your automatic refill order\b",
            r"\bautomatic refill order\b",
            r"\bordered\b",
        ),
        "Shipped": (
            r"\bshipped\b",
        ),
        "Out for delivery": (
            r"\bout for delivery\b",
        ),
        "Delivered": (
            r"\bdelivered\b",
        ),
    },
    "de": {
        "Ordered": (
            r"\bbestellt\b",
            r"\bbestellbestätigung\b",
            r"\bdanke für ihre bestellung\b",
            r"\bwir haben ihre bestellung erhalten\b",
            r"\bbestellung (?:bestätigt|aufgegeben)\b",
            r"\bihre amazon\.de[- ]bestellung\b",
            r"\bihre bestellung bei amazon\.de\b",
        ),
        "Shipped": (
            r"\bversandt\b",
            r"\bverschickt\b",
            r"\bversendet\b",
            r"\bunterwegs\b",
            r"\bauf de[mn] weg\b",
        ),
        "Out for delivery": (
            r"\bkommt heute\b",
            r"\bwird heute (?:zugestellt|geliefert)\b",
            r"\bin (?:der )?zustellung\b",
            r"\bzustellung heute\b",
        ),
        "Delivered": (
            r"\bzugestellt\b",
            r"\bgeliefert\b",
            r"\bangekommen\b",
            r"\babholbereit\b",
        ),
    },
}

STATUS_MATCH_ORDER = (
    "Out for delivery",
    "Delivered",
    "Shipped",
    "Ordered",
)


def _compile_status_patterns() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    """Compile localized status patterns in a precedence-safe order."""
    compiled = []
    for status in STATUS_MATCH_ORDER:
        for language, profile in LANGUAGE_PROFILES.items():
            for pattern in profile.get(status, ()):
                compiled.append((language, re.compile(pattern, re.IGNORECASE), status))
    return tuple(compiled)


STATUS_PATTERNS = _compile_status_patterns()

STATUS_RANKS = {
    "Ordered": 0,
    "Shipped": 1,
    "Out for delivery": 2,
    "Delivered": 3,
}


def _select_folder(mail: imaplib.IMAP4, folder: str) -> None:
    """Select an IMAP mailbox. Use standard select() when safe; otherwise send SELECT line ourselves.

    For names with space or parentheses, imaplib sends SELECT Test folder (unquoted), which
    FastMail rejects as 'Invalid modifier list'. Sending bytes via _command can be treated
    as a literal. So we build and send the exact line: TAG SELECT "folder"\r\n via mail.send(),
    then wait for the response and set state.
    """
    if any(c in folder for c in " ()"):
        mail.untagged_responses = {}
        quoted = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
        tag = mail._new_tag()
        tag_str = tag.decode("ascii") if isinstance(tag, bytes) else tag
        line = tag_str + " SELECT " + quoted + "\r\n"
        mail.send(line.encode("utf-8"))
        typ, data = mail._command_complete("SELECT", tag)
        if typ != "OK":
            msg = data[-1].decode("utf-8", "replace") if data and isinstance(data[-1], bytes) else str(data)
            raise mail.error(
                "Mailbox %r not found: %s. Check the folder name in integration options "
                "(case-sensitive). Use INBOX for the main inbox, or try a path like INBOX.Test folder."
                % (folder, msg)
            )
        mail.state = "SELECTED"
    else:
        mail.select(folder)


class AmazonOrdersCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch and track Amazon orders via email."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self._legacy_store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._orders: Dict[str, dict] = {}
        self.delivered_retention_days = int(entry.options.get("delivered_retention_days", 7))
        self._initial_scan_days = int(entry.options.get(CONF_INITIAL_SCAN_DAYS, 14))
        self._mark_as_read = entry.options.get(CONF_MARK_AS_READ, False)
        self._require_amazon_sender = entry.options.get(CONF_REQUIRE_AMAZON_SENDER, True)
        self.expose_order_id = entry.options.get(CONF_EXPOSE_ORDER_ID, True)
        self.expose_item_title = entry.options.get(CONF_EXPOSE_ITEM_TITLE, True)
        self.expose_tracking_url = entry.options.get(CONF_EXPOSE_TRACKING_URL, True)
        # Get IMAP folder from options, default to "INBOX" if empty or not set
        folder = entry.options.get(CONF_IMAP_FOLDER, "")
        self._imap_folder = folder.strip() if folder and folder.strip() else "INBOX"
        self.last_check: datetime | None = None
        self.last_scan_stats: dict = {}

        # Determine update interval from options or config entry, default 5 min
        interval_minutes = entry.options.get(
            "update_interval", entry.data.get("update_interval", 5)
        )

        super().__init__(
            hass,
            _LOGGER,
            name="Amazon Order Status",
            config_entry=entry,
            update_interval=timedelta(minutes=int(interval_minutes)),
        )

    """ Timestamp storage/retrieval functions to reduce email check time """
    async def _async_load_state(self) -> dict | None:
        """Load persisted state, falling back to the legacy global store key."""
        stored = await self._store.async_load()
        if stored:
            return stored

        legacy_stored = await self._legacy_store.async_load()
        if legacy_stored:
            _LOGGER.debug("Loaded legacy Amazon Order Status storage")
            return legacy_stored

        return None

    async def async_load_last_check(self) -> datetime | None:
        stored = await self._async_load_state()
        if stored and LAST_CHECK_KEY in stored:
            try:
                return datetime.fromisoformat(stored[LAST_CHECK_KEY])
            except (TypeError, ValueError):
                _LOGGER.warning("Stored Amazon Order Status last_check is invalid")
        return None

    async def async_load_stored_orders(self) -> None:
        """Load persisted orders from storage."""
        stored = await self._async_load_state()
        if stored:
            self._orders = stored.get(ORDERS_KEY, {})
            self._normalize_stored_orders()
            _LOGGER.debug("Loaded %d stored Amazon orders", len(self._orders))
        else:
            self._orders = {}
            _LOGGER.debug("No stored Amazon orders found")

    def _normalize_stored_orders(self) -> None:
        """Backfill new fields for orders saved by older integration versions."""
        for order in self._orders.values():
            subject = order.get("subject", "")
            item_title = order.get("item_title") or _extract_item_title(subject)
            if item_title:
                order["item_title"] = item_title
            order.setdefault("last_subject", subject)
            if not order.get("history") and order.get("status") and order.get("updated"):
                order["history"] = [
                    _history_entry(
                        order["status"],
                        order.get("last_subject") or subject,
                        order["updated"],
                        order.get("tracking_url"),
                    )
                ]

    async def async_save_state(self, last_check: datetime) -> None:
        await self._store.async_save(
            {
                LAST_CHECK_KEY: last_check.isoformat(),
                ORDERS_KEY: self._orders,
            }
        )

    def _current_data(self) -> list[dict]:
        """Return coordinator data including order IDs."""
        return [{**v, "order_id": k} for k, v in self._orders.items()]

    async def _async_update_data(self):
        _LOGGER.debug("Coordinator update triggered at %s", datetime.now(timezone.utc))

        if not self._orders:
            await self.async_load_stored_orders()

        last_check = await self.async_load_last_check()
        now = datetime.now(timezone.utc)

        scan_result = await self.hass.async_add_executor_job(
            self._fetch_and_parse_emails,
            last_check,
            now,
        )
        if not scan_result.success:
            raise UpdateFailed(f"Amazon order IMAP scan failed: {scan_result.error}")

        self.last_check = scan_result.processed_until

        # Purge old delivered orders
        self._purge_old_delivered_orders(scan_result.processed_until)

        await self.async_save_state(scan_result.processed_until)
        if (
            self.last_scan_stats.get("email_count", 0) > 0
            and self.last_scan_stats.get("recognized_count", 0) == 0
        ):
            _LOGGER.warning(
                "Amazon Order Status scanned %d emails in %s but recognized no order status emails",
                self.last_scan_stats["email_count"],
                self._imap_folder,
            )

        # Include order_id in each item so sensors and services can use it
        return self._current_data()

    @callback
    def _purge_old_delivered_orders(self, now: datetime):
        """Remove delivered orders older than retention period."""
        if not self._orders:
            return

        retention_cutoff = now - timedelta(days=self.delivered_retention_days)
        to_remove = []
        for order_id, order in self._orders.items():
            if order.get("status") != "Delivered":
                continue
            try:
                updated = datetime.fromisoformat(order.get("updated"))
            except (TypeError, ValueError):
                continue
            if _to_utc(updated) < retention_cutoff:
                to_remove.append(order_id)

        for order_id in to_remove:
            _LOGGER.debug(
                "Purging delivered order %s (older than %d days)",
                order_id,
                self.delivered_retention_days,
            )
            self._orders.pop(order_id, None)

    async def async_purge_order(self, order_id: str) -> bool:
        """Remove a specific order from tracking and persist state. Returns True if removed."""
        if order_id not in self._orders:
            return False
        self._orders.pop(order_id, None)
        _LOGGER.debug("Purged order %s by user request", order_id)
        now = self.last_check or datetime.now(timezone.utc)
        await self.async_save_state(now)
        self.async_set_updated_data(self._current_data())
        return True

    async def async_rescan(self, days: int = 14, clear_existing: bool = False) -> int:
        """Rescan a configurable lookback window and publish updated data."""
        days = max(1, min(int(days), 365))
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        previous_orders = dict(self._orders)

        if clear_existing:
            _LOGGER.debug("Clearing Amazon orders before %d-day rescan", days)
            self._orders = {}
        elif not self._orders:
            await self.async_load_stored_orders()

        _LOGGER.debug("Manual Amazon order rescan started for last %d days", days)
        scan_result = await self.hass.async_add_executor_job(
            self._fetch_and_parse_emails,
            since,
            now,
        )
        if not scan_result.success:
            if clear_existing:
                self._orders = previous_orders
            raise UpdateFailed(f"Amazon order rescan failed: {scan_result.error}")

        self.last_check = scan_result.processed_until
        self._purge_old_delivered_orders(scan_result.processed_until)
        await self.async_save_state(scan_result.processed_until)
        self.async_set_updated_data(self._current_data())
        _LOGGER.debug("Manual Amazon order rescan finished with %d tracked orders", len(self._orders))
        return len(self._orders)

    def _fetch_and_parse_emails(
        self,
        last_check: datetime | None,
        now: datetime,
    ) -> ScanResult:
        """Connect to IMAP and parse Amazon emails."""
        email_addr = self.entry.data["email"]
        password = self.entry.data["password"]
        imap_server = self.entry.data["imap_server"]
        imap_port = int(self.entry.data.get("imap_port", 993))
        mark_as_read = self._mark_as_read
        mail = None

        _LOGGER.debug(
            "Connecting to IMAP server %s:%d as %s",
            imap_server,
            imap_port,
            email_addr,
        )
        if last_check:
            since = last_check
            _LOGGER.debug("Checking emails since last run: %s", since)
        else:
            since = now - timedelta(days=self._initial_scan_days)
            _LOGGER.debug("First run: checking last %d days", self._initial_scan_days)

        scan_stats = _new_scan_stats(self._imap_folder, since, now)
        self.last_scan_stats = scan_stats

        try:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(email_addr, password)
            # Send SELECT with mailbox as a quoted string so IMAP4rev2 servers (e.g. FastMail)
            # do not misparse the command as having an invalid modifier list (RFC 9051).
            _select_folder(mail, self._imap_folder)
            _LOGGER.debug("Selected IMAP folder: %s", self._imap_folder)

            since_utc = _to_utc(since)
            # IMAP SINCE is interpreted in the server's timezone (e.g. Gmail uses PST), so
            # using the UTC date can ask for "future" emails and return 0. Use one day
            # earlier so we always fetch recent emails; we filter by since_utc in Python.
            since_date_imap = _imap_date_str(since_utc - timedelta(days=1))
            # No charset for date-only criterion; some servers reject CHARSET with SINCE
            typ, data = mail.search(None, f'(SINCE "{since_date_imap}")')

            if typ != "OK":
                _LOGGER.error("IMAP search failed")
                scan_stats["error"] = "imap_search_failed"
                return ScanResult(False, since, "imap_search_failed")

            email_nums = data[0].split()
            scan_stats["email_count"] = len(email_nums)
            _LOGGER.debug(
                "Found %d emails since %s (processing all; applying updates when email is newer than stored)",
                len(email_nums),
                since_date_imap,
            )

            for num in email_nums:
                typ, msg_data = mail.fetch(num, "(BODY.PEEK[] INTERNALDATE)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    _LOGGER.warning("Failed to fetch email %s", num)
                    scan_stats["failed_fetch_count"] += 1
                    continue
                scan_stats["fetched_count"] += 1

                # Prefer INTERNALDATE (when mailbox received the message) over Date header
                raw_response = msg_data[0][0]
                if isinstance(raw_response, bytes):
                    raw_response = raw_response.decode(errors="ignore")
                internaldate_utc = None
                internaldate_match = INTERNALDATE_RE.search(raw_response)
                if internaldate_match:
                    internaldate_utc = _parse_internaldate(internaldate_match.group(1))

                msg = message_from_bytes(msg_data[0][1])
                msg_date = msg.get("Date")
                msg_datetime = None
                if msg_date:
                    try:
                        msg_datetime = email.utils.parsedate_to_datetime(msg_date)
                    except (TypeError, ValueError):
                        msg_datetime = None
                    if msg_datetime is not None:
                        if msg_datetime.tzinfo is None:
                            msg_datetime = msg_datetime.replace(tzinfo=timezone.utc)
                        else:
                            msg_datetime = msg_datetime.astimezone(timezone.utc)

                received_utc = internaldate_utc if internaldate_utc is not None else msg_datetime
                if received_utc is None:
                    _LOGGER.debug("Email %s: no INTERNALDATE or Date header, skipping", num)
                    scan_stats["skipped_no_date"] += 1
                    continue

                # Ignore emails that arrived before our last check (avoids re-adding purged orders)
                if last_check is not None and received_utc < since_utc:
                    _LOGGER.debug(
                        "Email %s: received %s before last check %s, skipping",
                        num,
                        received_utc,
                        since_utc,
                    )
                    scan_stats["skipped_before_last_check"] += 1
                    continue

                if self._require_amazon_sender and not _message_from_amazon(msg):
                    _LOGGER.debug("Email %s: sender is not an allowed Amazon domain", num)
                    scan_stats["skipped_sender"] += 1
                    continue

                subject = self._decode_header(msg.get("Subject", ""))
                subject_lower = subject.lower()

                status = self._status_from_subject(subject_lower)
                if not status:
                    _LOGGER.debug(
                        "Email %s: subject not recognized as order status, skipping: %s",
                        num,
                        subject[:80],
                    )
                    scan_stats["skipped_no_status"] += 1
                    continue
                scan_stats["recognized_count"] += 1

                body_text = self._extract_text(msg)
                html_body = self._extract_html(msg)

                # Collect order IDs from both plain text and HTML; many "shipped" emails
                # put the order number only in the HTML part, so we must check both.
                order_ids = _extract_order_ids_from_text(subject, body_text, html_body)
                if not order_ids:
                    matched_order_ids = self._order_ids_for_subject_item(subject)
                    if len(matched_order_ids) == 1:
                        order_ids = matched_order_ids
                        _LOGGER.debug(
                            "Matched email without order number to existing order by subject"
                        )
                        scan_stats["matched_by_subject_count"] += 1
                    elif len(matched_order_ids) > 1:
                        _LOGGER.debug(
                            "Email %s: subject matched multiple active orders, skipping",
                            num,
                        )
                        scan_stats["skipped_ambiguous_subject_match"] += 1
                        continue
                if not order_ids:
                    _LOGGER.debug(
                        "No order numbers found in email. Checked plain text (%d chars) and HTML (%d chars).",
                        len(body_text),
                        len(html_body) if html_body else 0,
                    )
                    scan_stats["skipped_no_order_id"] += 1
                    continue

                tracking_url = self._extract_tracking_url(html_body) if html_body else None

                updated_ts = (msg_datetime if msg_datetime is not None else received_utc).isoformat()
                for order_id in order_ids:
                    # Only overwrite if we don't have this order or this email is newer than stored
                    existing = self._orders.get(order_id)
                    if existing:
                        existing_status_rank = STATUS_RANKS.get(existing.get("status"), -1)
                        new_status_rank = STATUS_RANKS.get(status, -1)
                        if new_status_rank < existing_status_rank:
                            _LOGGER.debug(
                                "Order %s: skipping status regression %s -> %s",
                                order_id,
                                existing.get("status"),
                                status,
                            )
                            scan_stats["skipped_status_regression"] += 1
                            continue
                        try:
                            existing_updated = _to_utc(
                                datetime.fromisoformat(existing["updated"])
                            )
                            if (
                                new_status_rank == existing_status_rank
                                and received_utc < existing_updated
                            ):
                                _LOGGER.debug(
                                    "Order %s: skipping older duplicate email",
                                    order_id,
                                )
                                scan_stats["skipped_older_duplicate"] += 1
                                continue
                        except (ValueError, TypeError):
                            pass

                    stored_subject = subject
                    stored_tracking_url = tracking_url
                    item_title = _extract_item_title(subject)
                    if existing:
                        existing_subject = existing.get("subject", "")
                        existing_item_title = existing.get("item_title") or _extract_item_title(
                            existing_subject
                        )
                        if item_title is None:
                            item_title = existing_item_title
                        if (
                            existing_item_title
                            and not _subject_item_key(subject)
                        ):
                            stored_subject = existing_subject
                        if stored_tracking_url is None:
                            stored_tracking_url = existing.get("tracking_url")

                    event = _history_entry(status, subject, updated_ts, tracking_url)
                    self._orders[order_id] = {
                        "status": status,
                        "subject": stored_subject,
                        "last_subject": subject,
                        "item_title": item_title,
                        "updated": updated_ts,
                        "tracking_url": stored_tracking_url,
                        "history": _append_history(existing, event),
                    }
                    scan_stats["updated_count"] += 1
                    _LOGGER.debug("Order %s -> %s", order_id, status)

                if mark_as_read:
                    _LOGGER.debug("Marking email %s as read (order email processed)", num)
                    mail.store(num, "+FLAGS", "\\Seen")

            return ScanResult(True, now)
        except imaplib.IMAP4.error as err:
            scan_stats["error"] = "imap_error"
            _LOGGER.warning("Amazon order IMAP error: %s", err)
            return ScanResult(False, since, "imap_error")
        except (OSError, socket.gaierror) as err:
            scan_stats["error"] = "connection_error"
            _LOGGER.warning("Amazon order IMAP connection error: %s", err)
            return ScanResult(False, since, "connection_error")
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except imaplib.IMAP4.error:
                    pass

    def _status_from_subject(self, subject: str) -> str | None:
        """Determine order status from email subject."""
        for _language, pattern, status in STATUS_PATTERNS:
            if pattern.search(subject):
                return status
        return None

    def _order_ids_for_subject_item(self, subject: str) -> list[str]:
        """Find existing tracked orders with the same item title in the subject."""
        item_key = _subject_item_key(subject)
        if not item_key:
            return []

        return [
            order_id
            for order_id, order in self._orders.items()
            if order.get("status") != "Delivered" and _order_item_key(order) == item_key
        ]

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
            href_lower = href.lower()

            # Case 1: Tracking links
            if (
                "track package" in text
                or "paket verfolgen" in text
                or "sendung verfolgen" in text
                or "lieferung verfolgen" in text
                or "progress-tracker" in href_lower
                or "ship-track" in href_lower
            ):
                match = re.search(
                    r"https://www\.amazon\.[^/\"&]+/"
                    r"(?:progress-tracker|gp/your-account/ship-track)/[^&\"]+",
                    href,
                )
                if match:
                    return _safe_amazon_url(match.group(0))
                return _safe_amazon_url(href)

            # Case 2: Order management links
            if (
                ("your-orders" in href_lower or "order-details" in href_lower)
                and (
                    "view" in text
                    or "edit order" in text
                    or "ansehen" in text
                    or "anzeigen" in text
                    or "details" in text
                    or "meine bestellungen" in text
                    or "bearbeiten" in text
                    or "ändern" in text
                )
            ):
                return _safe_amazon_url(href)

        return None
