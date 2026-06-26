"""Shipment-first model helpers for Amazon Order Status 2.0."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from urllib.parse import urlparse

AMAZON_DOMAIN_PATTERN = re.compile(
    r"(^|\.)amazon\."
    r"(com|de|co\.uk|fr|it|es|nl|se|pl|com\.be|com\.mx|ca|co\.jp|"
    r"com\.au|com\.tr|ae|sa|sg|in|com\.br)$",
    re.IGNORECASE,
)

SHIPMENT_STATUSES: tuple[str, ...] = (
    "Ordered",
    "Shipped",
    "Out for delivery",
    "Delivery attempted",
    "Pickup ready",
    "Delayed",
    "Delivery problem",
    "Undeliverable",
    "Delivered",
    "Canceled",
    "Return started",
    "Refunded",
    "Ignored",
)

ORDER_STATUSES: tuple[str, ...] = (
    "Ordered",
    "Shipped",
    "Out for delivery",
    "Delivery attempted",
    "Pickup ready",
    "Delayed",
    "Delivery problem",
    "Undeliverable",
    "Partially delivered",
    "Delivered",
    "Canceled",
    "Return started",
    "Refunded",
    "Ignored",
)

STATUS_SENSOR_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("ordered", "Ordered", "Ordered"),
    ("shipped", "Shipped", "Shipped"),
    ("out_for_delivery", "Out for delivery", "Out for delivery"),
    ("delivery_attempted", "Delivery attempted", "Delivery attempted"),
    ("pickup_ready", "Pickup ready", "Pickup ready"),
    ("delayed", "Delayed", "Delayed"),
    ("delivery_problem", "Delivery problem", "Delivery problem"),
    ("undeliverable", "Undeliverable", "Undeliverable"),
    ("partially_delivered", "Partially delivered", "Partially delivered"),
    ("delivered", "Delivered", "Delivered"),
    ("canceled", "Canceled", "Canceled"),
    ("return_started", "Return started", "Return started"),
    ("refunded", "Refunded", "Refunded"),
    ("ignored", "Ignored", "Ignored"),
)

ORDER_DETAIL_FIELDS: tuple[str, ...] = (
    "delivery_estimate",
    "delivery_date_start",
    "delivery_date_end",
    "delivery_window",
    "delivery_window_start",
    "delivery_window_end",
    "delivered_at",
    "delivery_is_delayed",
    "carrier",
    "item_count",
    "item_image_url",
    "parser_debug",
)

_ACTIVE_STATUS_RANKS = {
    "Ordered": 0,
    "Canceled": 0,
    "Shipped": 1,
    "Out for delivery": 2,
    "Delivery attempted": 3,
    "Delivered": 4,
    "Refunded": 4,
}


def _safe_tracking_url(tracking_url: str | None) -> str | None:
    if not tracking_url:
        return None

    parsed = urlparse(tracking_url)
    if parsed.scheme != "https" or not AMAZON_DOMAIN_PATTERN.search(parsed.hostname or ""):
        return None
    return tracking_url


def _tracking_suffix(tracking_url: str) -> str:
    parsed = urlparse(tracking_url)
    suffix = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    normalized = re.sub(r"[^a-z0-9]+", "-", suffix.lower()).strip("-")
    return normalized or "tracking"


def _shipment_subject(shipment: dict[str, Any]) -> str | None:
    history = shipment.get("history") or []
    if not history:
        return None
    return history[-1].get("subject")


def _rebuild_items(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for shipment in shipments:
        item_title = shipment.get("item_title")
        item_key = shipment.get("item_key") or item_title or shipment["shipment_id"]
        if item_key not in items:
            items[item_key] = {
                "item_key": shipment.get("item_key"),
                "item_title": item_title,
                "item_image_url": shipment.get("item_image_url"),
                "quantity": 0,
            }
        items[item_key]["quantity"] += int(shipment.get("item_count") or 1)
        if not items[item_key].get("item_image_url"):
            items[item_key]["item_image_url"] = shipment.get("item_image_url")
    return list(items.values())


def _rebuild_order_summary(order: dict[str, Any]) -> dict[str, Any]:
    shipments = order.get("shipments", [])
    order["status"] = rollup_order_status(shipments, ignored=bool(order.get("ignored")))
    order["item_count"] = sum(int(shipment.get("item_count") or 1) for shipment in shipments)
    order["items"] = _rebuild_items(shipments)

    if shipments:
        latest = max(shipments, key=lambda shipment: shipment.get("updated", ""))
        order["updated"] = latest.get("updated", order.get("updated"))
        latest_subject = _shipment_subject(latest)
        if latest_subject:
            order["last_subject"] = latest_subject
            order.setdefault("subject", latest_subject)

    order["manual"] = bool(order.get("manual")) or any(
        shipment.get("manual") for shipment in shipments
    )
    order["history"] = append_history(
        order.get("history", []),
        new_history_event(
            order["status"],
            order.get("updated", ""),
            reason="shipment_rollup",
        ),
    )
    return order


def shipment_id_for(
    order_id: str,
    item_key: str | None,
    tracking_url: str | None,
) -> str:
    """Build a deterministic shipment identifier."""
    if item_key:
        return f"{order_id}:{item_key}"

    safe_tracking_url = _safe_tracking_url(tracking_url)
    if safe_tracking_url:
        return f"{order_id}:{_tracking_suffix(safe_tracking_url)}"

    return f"{order_id}:default"


def new_history_event(
    status: str,
    updated: str,
    subject: str | None = None,
    tracking_url: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build one sanitized history event."""
    event: dict[str, Any] = {
        "status": status,
        "updated": updated,
    }
    if subject is not None:
        event["subject"] = subject
    safe_tracking_url = _safe_tracking_url(tracking_url)
    if safe_tracking_url is not None:
        event["tracking_url"] = safe_tracking_url
    if reason is not None:
        event["reason"] = reason
    return event


def append_history(existing: list[dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]]:
    """Append a history event if it is not already present."""
    history = list(existing or [])
    if event in history:
        return history
    history.append(event)
    return history


def rollup_order_status(shipments: list[dict[str, Any]], ignored: bool = False) -> str:
    """Roll up shipment statuses into one order status."""
    if ignored:
        return "Ignored"

    active_shipments = [shipment for shipment in shipments if not shipment.get("ignored")]
    if not active_shipments:
        return "Ignored" if shipments else "Ordered"

    statuses = [shipment.get("status", "Ordered") for shipment in active_shipments]

    if all(status == "Canceled" for status in statuses):
        return "Canceled"
    if all(status == "Refunded" for status in statuses):
        return "Refunded"
    if any(status == "Return started" for status in statuses):
        return "Return started"
    if any(status == "Undeliverable" for status in statuses):
        return "Undeliverable"
    if any(status == "Delivery problem" for status in statuses):
        return "Delivery problem"
    if any(status == "Delayed" for status in statuses):
        return "Delayed"
    if any(status == "Pickup ready" for status in statuses):
        return "Pickup ready"
    if all(status == "Delivered" for status in statuses):
        return "Delivered"
    if "Delivered" in statuses and any(status != "Delivered" for status in statuses):
        return "Partially delivered"

    return max(
        statuses,
        key=lambda status: _ACTIVE_STATUS_RANKS.get(status, -1),
    )


def build_shipment(
    order_id: str,
    status: str,
    updated: str,
    subject: str,
    item_key: str | None,
    item_title: str | None,
    tracking_url: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Build one shipment record."""
    shipment: dict[str, Any] = {
        "shipment_id": shipment_id_for(order_id, item_key, tracking_url),
        "status": status,
        "item_key": item_key,
        "item_title": item_title,
        "tracking_url": _safe_tracking_url(tracking_url),
        "updated": updated,
        "history": [
            new_history_event(
                status,
                updated,
                subject=subject,
                tracking_url=tracking_url,
            )
        ],
        "manual": False,
        "ignored": False,
    }
    for field in ORDER_DETAIL_FIELDS:
        if field == "delivery_is_delayed":
            shipment[field] = details.get(field, False)
            continue
        shipment[field] = deepcopy(details.get(field))
    return shipment


def build_order(
    order_id: str,
    shipment: dict[str, Any],
    subject: str,
    updated: str,
) -> dict[str, Any]:
    """Build one order record from its first shipment."""
    order = {
        "order_id": order_id,
        "status": shipment["status"],
        "subject": subject,
        "last_subject": subject,
        "updated": updated,
        "item_count": int(shipment.get("item_count") or 1),
        "items": [],
        "shipments": [shipment],
        "history": [
            new_history_event(
                shipment["status"],
                updated,
                reason="shipment_rollup",
            )
        ],
        "manual": False,
        "ignored": False,
    }
    return _rebuild_order_summary(order)


def upsert_shipment(order: dict[str, Any], shipment: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a shipment on an order and refresh the summary."""
    shipments = order.setdefault("shipments", [])
    for index, existing in enumerate(shipments):
        if existing.get("shipment_id") == shipment.get("shipment_id"):
            shipments[index] = shipment
            break
    else:
        shipments.append(shipment)

    return _rebuild_order_summary(order)


def set_manual_status(
    order: dict[str, Any],
    status: str,
    updated: str,
    shipment_id: str | None = None,
    delivered_at: str | None = None,
) -> bool:
    """Set a manual order or shipment status."""
    if shipment_id is None:
        changed = (
            order.get("status") != status
            or not order.get("manual")
            or order.get("updated") != updated
        )
        if not changed:
            return False
        order["status"] = status
        order["manual"] = True
        order["updated"] = updated
        order["history"] = append_history(
            order.get("history", []),
            new_history_event(status, updated, reason="manual_status"),
        )
        return True

    for shipment in order.get("shipments", []):
        if shipment.get("shipment_id") != shipment_id:
            continue
        changed = (
            shipment.get("status") != status
            or not shipment.get("manual")
            or shipment.get("updated") != updated
            or shipment.get("delivered_at") != delivered_at
        )
        if not changed:
            return False
        shipment["status"] = status
        shipment["manual"] = True
        shipment["updated"] = updated
        if delivered_at is not None:
            shipment["delivered_at"] = delivered_at
        shipment["history"] = append_history(
            shipment.get("history", []),
            new_history_event(status, updated, reason="manual_status"),
        )
        _rebuild_order_summary(order)
        return True
    return False


def set_ignored(
    order: dict[str, Any],
    ignored: bool,
    updated: str,
    shipment_id: str | None = None,
) -> bool:
    """Mark an order or shipment as ignored and refresh the rollup."""
    if shipment_id is None:
        changed = order.get("ignored") != ignored or order.get("updated") != updated
        if not changed:
            return False
        order["ignored"] = ignored
        order["updated"] = updated
        order["history"] = append_history(
            order.get("history", []),
            new_history_event(
                "Ignored" if ignored else order.get("status", "Ordered"),
                updated,
                reason="ignored" if ignored else "restored",
            ),
        )
        _rebuild_order_summary(order)
        return True

    for shipment in order.get("shipments", []):
        if shipment.get("shipment_id") != shipment_id:
            continue
        changed = shipment.get("ignored") != ignored or shipment.get("updated") != updated
        if not changed:
            return False
        shipment["ignored"] = ignored
        shipment["updated"] = updated
        shipment["history"] = append_history(
            shipment.get("history", []),
            new_history_event(
                "Ignored" if ignored else shipment.get("status", "Ordered"),
                updated,
                reason="ignored" if ignored else "restored",
            ),
        )
        _rebuild_order_summary(order)
        return True
    return False
