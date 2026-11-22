"""Binary sensors for Sagemcom Vodafone."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SagecomCoordinator
from .entity import SagecomEntity


BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="wan_status",
        name="WAN",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="wifi24",
        name="Wi-Fi 2.4 GHz",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:wifi",
    ),
    BinarySensorEntityDescription(
        key="wifi5",
        name="Wi-Fi 5 GHz",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:wifi",
    ),
)


class SagecomBinarySensor(SagecomEntity, BinarySensorEntity):
    """A Sagemcom router binary sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SagecomCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.host}-{description.key}"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "wan_status":
            value = data.get("wan_status")
            return bool(value and value.get("status") == "UP")
        if key in ("wifi24", "wifi5"):
            wireless = data.get("wireless")
            try:
                radio = wireless[0]["wireless"]["radio"]["24" if key == "wifi24" else "5"]
                return bool(radio.get("state"))
            except (KeyError, IndexError, TypeError):
                return False
        return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom binary sensors."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            SagecomBinarySensor(coordinator, description)
            for description in BINARY_SENSORS
        ]
    )
