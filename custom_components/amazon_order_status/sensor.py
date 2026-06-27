"""Amazon Orders sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AmazonOrdersCoordinator
from .models import STATUS_SENSOR_DEFINITIONS


@dataclass(frozen=True, kw_only=True)
class AmazonOrderSensorDescription(SensorEntityDescription):
    """Describe an Amazon order sensor."""

    status: str | None = None


SENSORS: tuple[AmazonOrderSensorDescription, ...] = tuple(
    AmazonOrderSensorDescription(key=key, name=name, status=status)
    for key, name, status in STATUS_SENSOR_DEFINITIONS
)

LAST_UPDATED_SENSOR = AmazonOrderSensorDescription(
    key="last_updated",
    name="Last Updated",
    device_class=SensorDeviceClass.TIMESTAMP,
)

RECORDER_ATTRIBUTE_MAX_BYTES = 16_384
RECORDER_ATTRIBUTE_TARGET_BYTES = 14_000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Amazon Order Status sensors."""
    coordinator: AmazonOrdersCoordinator = entry.runtime_data

    sensors: list[SensorEntity] = [
        AmazonOrderStatusSensor(coordinator, description) for description in SENSORS
    ]
    sensors.append(AmazonOrdersLastUpdatedSensor(coordinator, LAST_UPDATED_SENSOR))

    async_add_entities(sensors)


class AmazonOrderBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Amazon Order Status sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmazonOrdersCoordinator,
        description: AmazonOrderSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Amazon Orders",
            manufacturer="Amazon",
        )


class AmazonOrderStatusSensor(AmazonOrderBaseSensor):
    """Sensor representing Amazon orders in a specific status."""

    _attr_icon = "mdi:package-variant"

    @property
    def native_value(self) -> int:
        """Return number of orders in this status."""
        return len(self._orders_for_status())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return order details for this status."""
        orders = self._orders_for_status()
        return _recorder_safe_status_attributes(orders)

    def _orders_for_status(self) -> list[dict[str, Any]]:
        """Return orders matching this sensor's status."""
        if not self.coordinator.data:
            return []

        orders: list[dict[str, Any]] = []
        for data in self.coordinator.data:
            if data.get("status") != self.entity_description.status:
                continue

            orders.append(_build_exposed_order(self.coordinator, data))

        return orders


class AmazonOrdersLastUpdatedSensor(AmazonOrderBaseSensor):
    """Sensor showing when Amazon orders were last updated."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last successful update."""
        return getattr(self.coordinator, "last_check", None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostics for the most recent scan."""
        return dict(getattr(self.coordinator, "last_scan_stats", {}) or {})


def _build_exposed_order(
    coordinator: AmazonOrdersCoordinator,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Build one order attribute payload while respecting privacy options."""
    shipments = data.get("shipments", [])
    order: dict[str, Any] = {
        "status": data.get("status"),
        "updated": data.get("updated"),
        "shipment_count": data.get("shipment_count", len(shipments)),
        "shipments": _filtered_shipments(coordinator, shipments),
        "manual": bool(data.get("manual")),
        "ignored": bool(data.get("ignored")),
    }
    if coordinator.expose_item_title and coordinator.expose_order_id:
        order["subject"] = data.get("subject")
        order["last_subject"] = data.get("last_subject", data.get("subject"))
    if coordinator.expose_order_id:
        order["order_id"] = data.get("order_id")
    if coordinator.expose_item_title:
        order["item_title"] = data.get("item_title")
    if coordinator.expose_tracking_url:
        order["tracking_url"] = data.get("tracking_url")
    if coordinator.expose_delivery_details:
        for field in (
            "delivery_estimate",
            "delivery_window",
            "delivered_at",
            "item_count",
        ):
            order[field] = data.get(field)
    if coordinator.expose_carrier:
        order["carrier"] = data.get("carrier")
    if coordinator.expose_item_image:
        order["item_image_url"] = data.get("item_image_url")
    if coordinator.expose_parser_debug and "parser_debug" in data:
        order["parser_debug"] = data.get("parser_debug")

    order["history"] = _filtered_history(coordinator, data.get("history", []))
    return order


def _recorder_safe_status_attributes(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Return status attributes sized to stay below Home Assistant recorder limits."""
    base = _status_attribute_counts(orders)
    attributes = {**base, "orders": orders}
    if _attribute_bytes(attributes) <= RECORDER_ATTRIBUTE_TARGET_BYTES:
        return attributes

    limited = _fit_orders_within_attribute_budget(base, orders, compacted=False)
    if limited["orders"]:
        return limited

    compact_orders = [_compact_order_for_recorder(order) for order in orders]
    return _fit_orders_within_attribute_budget(base, compact_orders, compacted=True)


def _status_attribute_counts(orders: list[dict[str, Any]]) -> dict[str, int]:
    """Return count attributes that always reflect the full matching order set."""
    return {
        "order_count": len(orders),
        "shipment_count": sum(
            int(order.get("shipment_count") or len(order.get("shipments", [])))
            for order in orders
        ),
    }


def _fit_orders_within_attribute_budget(
    base: dict[str, int],
    orders: list[dict[str, Any]],
    *,
    compacted: bool,
) -> dict[str, Any]:
    """Return as many orders as fit within the recorder-safe attribute budget."""
    shown: list[dict[str, Any]] = []
    for order in orders:
        candidate = _limited_status_attributes(
            base,
            [*shown, order],
            total_orders=len(orders),
            compacted=compacted,
        )
        if _attribute_bytes(candidate) > RECORDER_ATTRIBUTE_TARGET_BYTES:
            break
        shown.append(order)

    return _limited_status_attributes(
        base,
        shown,
        total_orders=len(orders),
        compacted=compacted,
    )


def _limited_status_attributes(
    base: dict[str, int],
    orders: list[dict[str, Any]],
    *,
    total_orders: int,
    compacted: bool,
) -> dict[str, Any]:
    """Build status attributes with truncation metadata."""
    attributes: dict[str, Any] = {
        **base,
        "orders": orders,
        "orders_shown": len(orders),
        "orders_truncated": max(total_orders - len(orders), 0),
        "attribute_limit_bytes": RECORDER_ATTRIBUTE_MAX_BYTES,
    }
    if compacted:
        attributes["orders_compacted"] = True
    return attributes


def _compact_order_for_recorder(order: dict[str, Any]) -> dict[str, Any]:
    """Return an order payload without history lists for oversized attributes."""
    compact_order = {
        key: value
        for key, value in order.items()
        if key != "history"
    }
    shipments = compact_order.get("shipments")
    if isinstance(shipments, list):
        compact_order["shipments"] = [
            {
                key: value
                for key, value in shipment.items()
                if key != "history"
            }
            for shipment in shipments
            if isinstance(shipment, dict)
        ]
    return compact_order


def _attribute_bytes(attributes: dict[str, Any]) -> int:
    """Return the JSON byte size Home Assistant recorder will roughly persist."""
    return len(
        json.dumps(
            attributes,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _filtered_shipments(
    coordinator: AmazonOrdersCoordinator,
    shipments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return shipment payloads respecting privacy options."""
    filtered: list[dict[str, Any]] = []
    for shipment in shipments:
        item: dict[str, Any] = {
            "status": shipment.get("status"),
            "updated": shipment.get("updated"),
            "history": _filtered_history(coordinator, shipment.get("history", [])),
            "manual": bool(shipment.get("manual")),
            "ignored": bool(shipment.get("ignored")),
        }
        if coordinator.expose_order_id:
            item["shipment_id"] = shipment.get("shipment_id")
        if coordinator.expose_item_title:
            item["item_title"] = shipment.get("item_title")
        if coordinator.expose_tracking_url:
            item["tracking_url"] = shipment.get("tracking_url")
        if coordinator.expose_delivery_details:
            for field in (
                "delivery_estimate",
                "delivery_date_start",
                "delivery_date_end",
                "delivery_window",
                "delivery_window_start",
                "delivery_window_end",
                "delivered_at",
                "delivery_is_delayed",
                "item_count",
            ):
                item[field] = shipment.get(field)
        if coordinator.expose_carrier:
            item["carrier"] = shipment.get("carrier")
        if coordinator.expose_item_image:
            item["item_image_url"] = shipment.get("item_image_url")
        if coordinator.expose_parser_debug and "parser_debug" in shipment:
            item["parser_debug"] = shipment.get("parser_debug")
        filtered.append(item)
    return filtered


def _filtered_history(
    coordinator: AmazonOrdersCoordinator,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return history events respecting privacy options."""
    filtered: list[dict[str, Any]] = []
    for event in history:
        item: dict[str, Any] = {
            "status": event.get("status"),
            "updated": event.get("updated"),
        }
        if coordinator.expose_item_title and coordinator.expose_order_id:
            item["subject"] = event.get("subject")
        if coordinator.expose_tracking_url:
            item["tracking_url"] = event.get("tracking_url")
        filtered.append(item)
    return filtered
