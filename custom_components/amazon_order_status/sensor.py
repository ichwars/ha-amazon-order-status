"""Amazon Orders sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, kw_only=True)
class AmazonOrderSensorDescription(SensorEntityDescription):
    """Describe an Amazon order sensor."""

    status: str | None = None


SENSORS: tuple[AmazonOrderSensorDescription, ...] = (
    AmazonOrderSensorDescription(key="ordered", name="Ordered", status="Ordered"),
    AmazonOrderSensorDescription(key="shipped", name="Shipped", status="Shipped"),
    AmazonOrderSensorDescription(
        key="out_for_delivery",
        name="Out for delivery",
        status="Out for delivery",
    ),
    AmazonOrderSensorDescription(key="delivered", name="Delivered", status="Delivered"),
)

LAST_UPDATED_SENSOR = AmazonOrderSensorDescription(
    key="last_updated",
    name="Last Updated",
    device_class=SensorDeviceClass.TIMESTAMP,
)


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
        return {
            "order_count": len(orders),
            "orders": orders,
        }

    def _orders_for_status(self) -> list[dict[str, Any]]:
        """Return orders matching this sensor's status."""
        if not self.coordinator.data:
            return []

        orders: list[dict[str, Any]] = []
        for data in self.coordinator.data:
            if data.get("status") != self.entity_description.status:
                continue

            order: dict[str, Any] = {
                "status": data.get("status"),
                "updated": data.get("updated"),
            }
            if self.coordinator.expose_item_title and self.coordinator.expose_order_id:
                order["subject"] = data.get("subject")
                order["last_subject"] = data.get(
                    "last_subject",
                    data.get("subject"),
                )
            if self.coordinator.expose_order_id:
                order["order_id"] = data.get("order_id")
            if self.coordinator.expose_item_title:
                order["item_title"] = data.get("item_title")
            if self.coordinator.expose_tracking_url:
                order["tracking_url"] = data.get("tracking_url")
            order["history"] = self._filtered_history(data.get("history", []))
            orders.append(order)

        return orders

    def _filtered_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return history events respecting privacy options."""
        filtered: list[dict[str, Any]] = []
        for event in history:
            item: dict[str, Any] = {
                "status": event.get("status"),
                "updated": event.get("updated"),
            }
            if self.coordinator.expose_item_title and self.coordinator.expose_order_id:
                item["subject"] = event.get("subject")
            if self.coordinator.expose_tracking_url:
                item["tracking_url"] = event.get("tracking_url")
            filtered.append(item)
        return filtered


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
