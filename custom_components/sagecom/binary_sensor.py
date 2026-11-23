"""Binary sensors for Sagemcom F@st CPE."""

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
        if key == "hotspot5":
            stats = data.get("hotspot5_stats")
            try:
                return bool(stats[0]["wireless"]["ssid"]["status"])
            except (KeyError, IndexError, TypeError):
                return False
        if key.startswith("eth_"):
            port_key = key[4:]
            port = (data.get("ethernet_ports") or {}).get(port_key)
            return bool(port and port.get("up"))
        return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom binary sensors."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data or {}
    entities: list[SagecomBinarySensor] = []

    for description in BINARY_SENSORS:
        if description.key == "wan_status" and data.get("wan_status") is not None:
            entities.append(SagecomBinarySensor(coordinator, description))
        elif description.key in ("wifi24", "wifi5"):
            band = "24" if description.key == "wifi24" else "5"
            try:
                if band in data["wireless"][0]["wireless"]["radio"]:
                    entities.append(SagecomBinarySensor(coordinator, description))
            except (KeyError, IndexError, TypeError):
                pass

    if data.get("hotspot5_stats") is not None:
        entities.append(
            SagecomBinarySensor(
                coordinator,
                BinarySensorEntityDescription(
                    key="hotspot5",
                    name="Hotspot 5 GHz",
                    device_class=BinarySensorDeviceClass.CONNECTIVITY,
                    icon="mdi:wifi",
                ),
            )
        )

    eth_ports = data.get("ethernet_ports")
    if isinstance(eth_ports, dict):
        for port_key, port in eth_ports.items():
            alias = port.get("alias") or port_key.upper()
            entities.append(
                SagecomBinarySensor(
                    coordinator,
                    BinarySensorEntityDescription(
                        key=f"eth_{port_key}",
                        name=f"Ethernet {alias}",
                        device_class=BinarySensorDeviceClass.CONNECTIVITY,
                        icon="mdi:ethernet",
                    ),
                )
            )

    async_add_entities(entities)
