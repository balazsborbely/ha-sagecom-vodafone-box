"""Sensors for Sagemcom Vodafone."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SagecomCoordinator
from .entity import SagecomEntity


SENSORS = (
    SensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="s",
        icon="mdi:timer-outline",
    ),
    SensorEntityDescription(
        key="firmware",
        name="Firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:update",
    ),
    SensorEntityDescription(
        key="model",
        name="Model",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:router-network",
    ),
    SensorEntityDescription(
        key="public_ipv4",
        name="Public IPv4",
        icon="mdi:ip-network",
    ),
    SensorEntityDescription(
        key="cable_modem_status",
        name="Cable modem status",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:cable-data",
    ),
    SensorEntityDescription(
        key="active_clients",
        name="Active clients",
        native_unit_of_measurement="clients",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-multiple",
    ),
    SensorEntityDescription(
        key="wifi24_rx_bytes",
        name="Wi-Fi 2.4 GHz received",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:wifi",
    ),
    SensorEntityDescription(
        key="wifi24_tx_bytes",
        name="Wi-Fi 2.4 GHz transmitted",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:wifi-arrow-up",
    ),
    SensorEntityDescription(
        key="wifi5_rx_bytes",
        name="Wi-Fi 5 GHz received",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:wifi",
    ),
    SensorEntityDescription(
        key="wifi5_tx_bytes",
        name="Wi-Fi 5 GHz transmitted",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:wifi-arrow-up",
    ),
)


def _nested(data: dict, *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _payload(data: dict, name: str) -> Any:
    return data.get(name)


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def _average(values: list[Any]) -> float | None:
    numeric = [_numeric(value) for value in values]
    numeric = [value for value in numeric if value is not None]
    return sum(numeric) / len(numeric) if numeric else None


class SagecomSensor(SagecomEntity, SensorEntity):
    """A Sagemcom router sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: SagecomCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.api.host}-{description.key}"
        )

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        device = _payload(data, "device")
        try:
            device_payload = device[0]["device"]
        except (KeyError, IndexError, TypeError):
            device_payload = {}

        key = self.entity_description.key
        if key == "uptime":
            return device_payload.get("uptime")
        if key == "firmware":
            return (
                device_payload.get("running", {}).get("version")
                or device_payload.get("main", {}).get("version")
            )
        if key == "model":
            return device_payload.get("modelname")
        if key == "public_ipv4":
            network = _payload(data, "docsis_network")
            return network[0].get("publicIpv4") if network else None
        if key == "cable_modem_status":
            network = _payload(data, "docsis_network")
            return network[0].get("cableModemStatus") if network else None
        if key == "active_clients":
            hosts_payload = _payload(data, "hosts")
            if hosts_payload:
                try:
                    hosts_payload = hosts_payload[0]["hosts"]["list"]
                except (KeyError, IndexError, TypeError):
                    hosts_payload = []
            else:
                hosts_payload = []
            if not isinstance(hosts_payload, list):
                hosts_payload = []
            return sum(bool(host.get("active")) for host in hosts_payload)

        for prefix, band in (("wifi24", "24"), ("wifi5", "5")):
            if key in (f"{prefix}_rx_bytes", f"{prefix}_tx_bytes"):
                wireless = _payload(data, f"wireless{band}_stats")
                direction = "rx" if key.endswith("rx_bytes") else "tx"
                try:
                    return wireless[0]["wireless"]["ssid"]["stats"][direction]["bytes"]
                except (KeyError, IndexError, TypeError):
                    return None
        if key in ("upstream_power", "downstream_power", "downstream_snr"):
            docsis = _payload(data, "docsis_connection")
            if not docsis:
                return None
            try:
                payload = docsis[0]
            except (IndexError, TypeError):
                return None
            if key == "upstream_power":
                return _average(
                    [channel.get("PowerLevel") for channel in payload.get("Upstreams", [])]
                )
            if key == "downstream_power":
                return _average(
                    [channel.get("PowerLevel") for channel in payload.get("Downstreams", [])]
                )
            return _average(
                [channel.get("SNR") for channel in payload.get("Downstreams", [])]
            )
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom sensors."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    sensors = [SagecomSensor(coordinator, description) for description in SENSORS]

    data = coordinator.data or {}
    docsis = _payload(data, "docsis_connection")
    if docsis:
        upstream = docsis[0].get("Upstreams", [])
        downstream = docsis[0].get("Downstreams", [])
        if upstream:
            sensors.append(
                SagecomSensor(
                    coordinator,
                    SensorEntityDescription(
                        key="upstream_power",
                        name="Upstream average power",
                        native_unit_of_measurement="dBmV",
                        state_class=SensorStateClass.MEASUREMENT,
                        icon="mdi:signal",
                    ),
                )
            )
        if downstream:
            sensors.extend(
                (
                    SagecomSensor(
                        coordinator,
                        SensorEntityDescription(
                            key="downstream_power",
                            name="Downstream average power",
                            native_unit_of_measurement="dBmV",
                            state_class=SensorStateClass.MEASUREMENT,
                            icon="mdi:signal",
                        ),
                    ),
                    SagecomSensor(
                        coordinator,
                        SensorEntityDescription(
                            key="downstream_snr",
                            name="Downstream average SNR",
                            native_unit_of_measurement="dB",
                            state_class=SensorStateClass.MEASUREMENT,
                            icon="mdi:signal",
                        ),
                    ),
                )
            )

    async_add_entities(sensors)
