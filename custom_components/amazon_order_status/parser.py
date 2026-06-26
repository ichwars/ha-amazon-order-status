"""Amazon order parser helpers for status and delivery details."""

from __future__ import annotations

from datetime import datetime, timedelta
import email.utils
import html
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urlparse

from .models import ORDER_DETAIL_FIELDS

ORDER_ID_REGEXES = (
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
AMAZON_IMAGE_DOMAIN_PATTERN = re.compile(
    r"(^|\.)("
    r"media-amazon\.com|ssl-images-amazon\.com|images-amazon\.com"
    r")$",
    re.IGNORECASE,
)

GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

LANGUAGE_PROFILES = {
    "en": {
        "Delivery problem": (
            r"\baction required for your delivery\b",
            r"\bproblem with your delivery\b",
        ),
        "Undeliverable": (
            r"\bundeliverable(?: package)?\b",
        ),
        "Return started": (
            r"\breturn started\b",
        ),
        "Refunded": (
            r"\brefund issued\b",
            r"\brefunded\b",
        ),
        "Canceled": (
            r"\bcancelled: your amazon order\b",
            r"\bcanceled: your amazon order\b",
        ),
        "Pickup ready": (
            r"\bpickup available\b",
            r"\bready for pickup\b",
        ),
        "Delayed": (
            r"\byour package is running late\b",
            r"\brunning late\b",
            r"\bdelayed\b",
        ),
        "Out for delivery": (
            r"\bout for delivery\b",
        ),
        "Delivery attempted": (
            r"\battempted delivery\b",
            r"\bdelivery attempted\b",
        ),
        "Delivered": (
            r"\bdelivered\b",
        ),
        "Shipped": (
            r"\bshipped\b",
        ),
        "Ordered": (
            r"\bsuccessfully placed your order\b",
            r"\bwe've received your order\b",
            r"\bpreparing your automatic refill order\b",
            r"\bautomatic refill order\b",
            r"\bordered\b",
        ),
    },
    "de": {
        "Delivery problem": (
            r"\bproblem mit deiner lieferung\b",
            r"\baktion erforderlich.*lieferung\b",
        ),
        "Undeliverable": (
            r"\bunzustellbar\b",
        ),
        "Return started": (
            r"\brücksendung gestartet\b",
        ),
        "Refunded": (
            r"\berstattung veranlasst\b",
            r"\berstattung erfolgt\b",
        ),
        "Canceled": (
            r"\bstorniert\b",
        ),
        "Pickup ready": (
            r"\babholbereit\b",
            r"\babholstation\b",
        ),
        "Delayed": (
            r"\blieferung ist verspätet\b",
        ),
        "Out for delivery": (
            r"\bkommt heute\b",
            r"\bwird heute (?:zugestellt|geliefert)\b",
            r"\bin (?:der )?zustellung\b",
            r"\bzustellung heute\b",
        ),
        "Delivery attempted": (
            r"\bzustellversuch\b",
            r"\bversuchte zustellung\b",
            r"\bzustellung wurde versucht\b",
        ),
        "Delivered": (
            r"\bzugestellt\b",
            r"\bgeliefert\b",
            r"\bangekommen\b",
        ),
        "Shipped": (
            r"\bversandt\b",
            r"\bverschickt\b",
            r"\bversendet\b",
            r"\bunterwegs\b",
            r"\bauf de[mn] weg\b",
        ),
        "Ordered": (
            r"\bbestellt\b",
            r"\bbestellbestätigung\b",
            r"\bdanke für ihre bestellung\b",
            r"\bwir haben ihre bestellung erhalten\b",
            r"\bbestellung (?:bestätigt|aufgegeben)\b",
            r"\bihre amazon\.de[- ]bestellung\b",
            r"\bihre bestellung bei amazon\.de\b",
        ),
    },
}

STATUS_MATCH_ORDER = (
    "Delivery problem",
    "Undeliverable",
    "Return started",
    "Refunded",
    "Canceled",
    "Pickup ready",
    "Delayed",
    "Out for delivery",
    "Delivery attempted",
    "Delivered",
    "Shipped",
    "Ordered",
)

STATUS_RANKS = {
    "Ordered": 0,
    "Shipped": 1,
    "Out for delivery": 2,
    "Delivery attempted": 3,
    "Pickup ready": 3,
    "Delayed": 3,
    "Delivery problem": 3,
    "Undeliverable": 3,
    "Delivered": 4,
    "Canceled": 4,
    "Return started": 4,
    "Refunded": 4,
}


def _compile_status_patterns() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    compiled = []
    for status in STATUS_MATCH_ORDER:
        for language, profile in LANGUAGE_PROFILES.items():
            for pattern in profile.get(status, ()):
                compiled.append((language, re.compile(pattern, re.IGNORECASE), status))
    return tuple(compiled)


STATUS_PATTERNS = _compile_status_patterns()


class _BodyHTMLParser(HTMLParser):
    """Extract small, safe parsing hints from Amazon email HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return

        attr = {key.lower(): value or "" for key, value in attrs}
        src = attr.get("src") or attr.get("data-src") or ""
        if src:
            self.images.append(
                {
                    "src": html.unescape(src),
                    "alt": clean_text(attr.get("alt", "")),
                    "width": attr.get("width", ""),
                    "height": attr.get("height", ""),
                }
            )

    def handle_data(self, data: str) -> None:
        clean = clean_text(data)
        if clean:
            self.text_parts.append(clean)


def extract_order_ids_from_text(*texts: str) -> list[str]:
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
    if not domain:
        return False
    return AMAZON_DOMAIN_PATTERN.search(domain.lower().strip(".")) is not None


def message_from_amazon(msg) -> bool:
    """Return True when sender headers point at an Amazon domain."""
    addresses: list[str] = []
    for header in ("From", "Sender", "Reply-To", "Return-Path"):
        value = msg.get(header)
        if value:
            addresses.extend(address for _name, address in email.utils.getaddresses([value]))

    for address in addresses:
        if "@" not in address:
            continue
        if _domain_is_amazon(address.rsplit("@", 1)[-1]):
            return True
    return False


def safe_amazon_url(href: str | None) -> str | None:
    """Return href only when it is an HTTPS Amazon URL."""
    if not href:
        return None

    parsed = urlparse(href)
    if parsed.scheme != "https" or not _domain_is_amazon(parsed.hostname):
        return None
    return href


def _domain_is_amazon_image(domain: str | None) -> bool:
    if not domain:
        return False
    return AMAZON_IMAGE_DOMAIN_PATTERN.search(domain.lower().strip(".")) is not None


def safe_amazon_image_url(src: str | None) -> str | None:
    """Return image src only when it is an HTTPS Amazon image URL."""
    if not src:
        return None

    parsed = urlparse(html.unescape(src))
    if parsed.scheme != "https" or not _domain_is_amazon_image(parsed.hostname):
        return None
    return html.unescape(src)


def clean_text(value: str | None) -> str:
    """Normalize whitespace and invisible Unicode markers from email text."""
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _html_summary(html_body: str) -> _BodyHTMLParser:
    parser = _BodyHTMLParser()
    if html_body:
        parser.feed(html_body)
    return parser


def _image_dimension(value: str) -> int:
    try:
        return int(re.sub(r"[^0-9]", "", value or "0") or "0")
    except ValueError:
        return 0


def _is_ignored_image_alt(alt: str) -> bool:
    alt_lower = alt.lower()
    return (
        not alt
        or alt_lower in {"amazon.de", "amazon", "ausstehend", "abgeschlossen"}
        or "icon" in alt_lower
        or "logo" in alt_lower
    )


def _extract_body_image_and_title(html_body: str) -> tuple[str | None, str | None, int]:
    parser = _html_summary(html_body)
    best: tuple[int, str | None, str | None] = (-1, None, None)

    for image in parser.images:
        safe_src = safe_amazon_image_url(image.get("src"))
        if not safe_src:
            continue

        parsed = urlparse(safe_src)
        alt = clean_text(image.get("alt"))
        width = _image_dimension(image.get("width", ""))
        height = _image_dimension(image.get("height", ""))
        path = parsed.path.lower()
        score = 0
        if "/images/i/" in path:
            score += 50
        if width >= 80:
            score += 20
        if height and height <= 30:
            score -= 20
        if "pixel" in path or "logo" in path or "/images/g/" in path:
            score -= 40
        if not _is_ignored_image_alt(alt):
            score += 30

        if score > best[0]:
            best = (score, safe_src, None if _is_ignored_image_alt(alt) else alt)

    if best[0] < 20:
        return None, None, len(parser.images)
    return best[1], best[2], len(parser.images)


def _combined_body_text(body_text: str, html_body: str) -> str:
    parser = _html_summary(html_body)
    body_lines = [clean_text(line) for line in body_text.splitlines()]
    parts = [line for line in body_lines if line]
    parts.extend(parser.text_parts)
    return "\n".join(part for part in parts if part)


def _extract_item_count_from_text(text: str) -> int | None:
    match = re.search(r"\b([0-9]+)\s*(?:artikel|article|item)s?\b", text, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_delivery_estimate_from_text(text: str) -> str | None:
    ignored_prefixes = (
        "bestellt:",
        "versendet:",
        "in zustellung:",
        "zugestellt:",
        "zustellversuch:",
    )
    for line in (clean_text(line) for line in text.splitlines()):
        line_lower = line.lower()
        if not line or line_lower.startswith(ignored_prefixes):
            continue

        for pattern in (
            r"^Zustellung:\s*(.+)$",
            r"^Lieferung:\s*(.+)$",
            r"^Arriving\s+(.+)$",
            r"^Ankunft\s+(heute|morgen)(?:\s|$)",
            r"^(?:kommt|ankunft)\s+(heute|morgen)\b",
        ):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return clean_text(match.group(1)).rstrip(".")
    if re.search(
        r"\bLieferung ist verspätet\b|\bLieferung deiner Bestellung\b",
        text,
        re.IGNORECASE,
    ):
        return "verzögert"
    if re.search(r"\brunning late\b|\bdelayed\b", text, re.IGNORECASE):
        return "delayed"
    return None


def _extract_delivery_window_from_text(text: str) -> str | None:
    for line in (clean_text(line) for line in text.splitlines()):
        match = re.search(
            r"\b(?:Ankunft|Zustellung|Lieferung|Arriving)\s+(?:today|tomorrow|heute|morgen)?\s*"
            r"([0-9]{1,2}(?::[0-9]{2})?\s*h?\s*[–-]\s*[0-9]{1,2}(?::[0-9]{2})?\s*h?)",
            line,
            re.IGNORECASE,
        )
        if match:
            return clean_text(match.group(1)).rstrip(".")
    return None


def _extract_delivered_at_from_text(text: str) -> str | None:
    for line in (clean_text(line) for line in text.splitlines()):
        match = re.search(
            r"\bVersuchte Zustellung[ \t]+([^\n\r.]+)",
            line,
            re.IGNORECASE,
        )
        if match:
            return clean_text(match.group(1))
        match = re.search(r"\bZugestellt[ \t]+um[ \t]+([0-9]{1,2}:[0-9]{2})", line, re.IGNORECASE)
        if match:
            return f"um {match.group(1)}"
        if re.search(r"\bHeute zugestellt\b", line, re.IGNORECASE):
            return "heute"
    return None


def _extract_carrier_from_text(text: str) -> str | None:
    carriers = (
        "Amazon Logistics",
        "DHL",
        "Deutsche Post",
        "Hermes",
        "UPS",
        "DPD",
        "GLS",
    )
    for carrier in carriers:
        if re.search(rf"\b{re.escape(carrier)}\b", text, re.IGNORECASE):
            return carrier
    return None


def status_from_subject(subject: str) -> str | None:
    """Determine order status from a localized email subject."""
    for _language, pattern, status in STATUS_PATTERNS:
        if pattern.search(subject):
            return status
    return None


def is_delivery_update_subject(subject_lower: str) -> bool:
    """Return True for delivery update emails that may not contain a tracked status."""
    return any(
        re.search(pattern, subject_lower, re.IGNORECASE)
        for pattern in (
            r"aktualisierung der voraussichtlichen lieferung",
            r"lieferung ist verspätet",
            r"delivery update",
            r"estimated delivery",
        )
    )


def extract_item_title(subject: str) -> str | None:
    """Extract a human-readable item title from Amazon status subjects."""
    subject = clean_text(subject)
    match = re.search(r"^[^:]+:\s*[„\"“]?(.+?)[”\"“]?$", subject)
    if not match:
        return None

    item = clean_text(match.group(1))
    item = re.split(r"\s+-\s+amazon\.", item, maxsplit=1, flags=re.IGNORECASE)[0]
    item_lower = item.lower()
    if "bestellung #" in item_lower or re.search(r"\bartikel\s*\|", item_lower):
        return None

    item = item.strip(" „\"“”")
    return item or None


def normalize_item_key(item_title: str | None) -> str | None:
    """Normalize an item title for matching related Amazon status emails."""
    if not item_title:
        return None

    item = re.sub(r"\.\.\.|…", " ", item_title.lower())
    item = re.sub(r"[^a-z0-9äöüß]+", " ", item)
    item = re.sub(r"\s+", " ", item).strip()
    return item or None


def _normalize_time_value(value: str) -> str | None:
    match = re.fullmatch(r"([0-9]{1,2})(?::([0-9]{2}))?\s*h?", clean_text(value), re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _extract_window_bounds(delivery_window: str | None) -> tuple[str | None, str | None]:
    if not delivery_window:
        return None, None
    match = re.search(
        r"([0-9]{1,2}(?::[0-9]{2})?\s*h?)\s*[–-]\s*([0-9]{1,2}(?::[0-9]{2})?\s*h?)",
        delivery_window,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return _normalize_time_value(match.group(1)), _normalize_time_value(match.group(2))


def _resolve_relative_date(keyword: str, received_at: datetime | None) -> str | None:
    if received_at is None:
        return None
    date_value = received_at.date()
    if keyword.lower() in {"tomorrow", "morgen"}:
        date_value = date_value + timedelta(days=1)
    return date_value.isoformat()


def _date_with_year(month: int, day: int, received_at: datetime | None) -> str | None:
    if received_at is None:
        return None
    year = received_at.year
    try:
        return datetime(year, month, day, tzinfo=received_at.tzinfo).date().isoformat()
    except ValueError:
        return None


def _extract_structured_delivery_dates(
    combined_text: str,
    delivery_estimate: str | None,
    received_at: datetime | None,
) -> tuple[str | None, str | None]:
    search_text = delivery_estimate or combined_text

    relative = re.search(r"\b(today|tomorrow|heute|morgen)\b", search_text, re.IGNORECASE)
    if relative:
        iso_date = _resolve_relative_date(relative.group(1), received_at)
        return iso_date, iso_date

    range_match = re.search(
        r"\b([0-9]{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s*-\s*([0-9]{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\b",
        search_text,
        re.IGNORECASE,
    )
    if range_match:
        start_month = GERMAN_MONTHS.get(clean_text(range_match.group(2)).lower())
        end_month = GERMAN_MONTHS.get(clean_text(range_match.group(4)).lower())
        if start_month and end_month:
            return (
                _date_with_year(start_month, int(range_match.group(1)), received_at),
                _date_with_year(end_month, int(range_match.group(3)), received_at),
            )

    single_match = re.search(
        r"\b([0-9]{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\b",
        search_text,
        re.IGNORECASE,
    )
    if single_match:
        month = GERMAN_MONTHS.get(clean_text(single_match.group(2)).lower())
        if month:
            iso_date = _date_with_year(month, int(single_match.group(1)), received_at)
            return iso_date, iso_date

    return None, None


def parse_body_details(
    subject: str,
    body_text: str,
    html_body: str,
    received_at: datetime | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Extract targeted order details from email body without storing raw content."""
    combined_text = _combined_body_text(body_text, html_body)
    image_url, image_title, image_count = _extract_body_image_and_title(html_body)
    details: dict[str, Any] = {}

    item_title = image_title or extract_item_title(subject)
    if item_title:
        details["item_title"] = item_title

    item_count = _extract_item_count_from_text(f"{subject}\n{combined_text}")
    if item_count is not None:
        details["item_count"] = item_count

    delivery_estimate = _extract_delivery_estimate_from_text(combined_text)
    if delivery_estimate:
        details["delivery_estimate"] = delivery_estimate

    delivery_window = _extract_delivery_window_from_text(combined_text)
    if delivery_window:
        details["delivery_window"] = delivery_window
        window_start, window_end = _extract_window_bounds(delivery_window)
        if window_start:
            details["delivery_window_start"] = window_start
        if window_end:
            details["delivery_window_end"] = window_end

    date_start, date_end = _extract_structured_delivery_dates(
        combined_text,
        delivery_estimate,
        received_at,
    )
    if date_start:
        details["delivery_date_start"] = date_start
    if date_end:
        details["delivery_date_end"] = date_end

    delivered_at = _extract_delivered_at_from_text(combined_text)
    if delivered_at:
        details["delivered_at"] = delivered_at

    carrier = _extract_carrier_from_text(combined_text)
    if carrier:
        details["carrier"] = carrier

    if status_from_subject(subject.lower()) == "Delayed" or delivery_estimate in {
        "verzögert",
        "delayed",
    }:
        details["delivery_is_delayed"] = True

    if image_url:
        details["item_image_url"] = image_url

    if include_debug:
        details["parser_debug"] = {
            "source": "body_details",
            "fields": sorted(details),
            "image_candidates": image_count,
            "has_body_text": bool(combined_text),
        }

    allowed_keys = set(ORDER_DETAIL_FIELDS) | {"item_title"}
    return {key: value for key, value in details.items() if key in allowed_keys}
