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
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfTemperature,
)
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
        if key in ("wan_rx_bytes", "wan_tx_bytes"):
            wan_stats = _payload(data, "wan_stats")
            if not isinstance(wan_stats, dict):
                return None
            return wan_stats.get("rx_bytes" if key == "wan_rx_bytes" else "tx_bytes")
        if key in (
            "wan_daily_rx_bytes",
            "wan_daily_tx_bytes",
            "wan_quarter_hour_rx_bytes",
            "wan_quarter_hour_tx_bytes",
        ):
            wan_stats = _payload(data, "wan_stats")
            if not isinstance(wan_stats, dict):
                return None
            field_map = {
                "wan_daily_rx_bytes": "daily_rx_bytes",
                "wan_daily_tx_bytes": "daily_tx_bytes",
                "wan_quarter_hour_rx_bytes": "quarter_hour_rx_bytes",
                "wan_quarter_hour_tx_bytes": "quarter_hour_tx_bytes",
            }
            return wan_stats.get(field_map[key])
        if key in ("lan_rx_bytes", "lan_tx_bytes"):
            lan_stats = _payload(data, "lan_stats")
            if not isinstance(lan_stats, dict):
                return None
            return lan_stats.get("rx_bytes" if key == "lan_rx_bytes" else "tx_bytes")
        if key in (
            "memory_usage_pct",
            "memory_free_kb",
            "load_1m",
            "load_5m",
            "load_15m",
            "reboot_count",
        ):
            sys_stats = _payload(data, "system_stats")
            return sys_stats.get(key) if isinstance(sys_stats, dict) else None
        if key in (
            "optical_rx_power",
            "optical_tx_power",
            "optical_temperature",
            "optical_voltage",
            "optical_bias_current",
            "gpon_state",
            "optical_alarm",
        ):
            opt = _payload(data, "optical")
            if not isinstance(opt, dict):
                return None
            opt_map = {
                "optical_rx_power": "rx_power_dbm",
                "optical_tx_power": "tx_power_dbm",
                "optical_temperature": "temperature_c",
                "optical_voltage": "voltage_v",
                "optical_bias_current": "bias_current_ma",
                "gpon_state": "gpon_state",
                "optical_alarm": "alarm",
            }
            return opt.get(opt_map[key])
        for band_prefix, band_key in (("wifi24", "24"), ("wifi5", "5")):
            if key in (
                f"{band_prefix}_channel",
                f"{band_prefix}_noise",
                f"{band_prefix}_clients",
            ):
                details = (_payload(data, "wifi_details") or {}).get(band_key)
                if not isinstance(details, dict):
                    return None
                if key.endswith("_channel"):
                    return details.get("channel")
                if key.endswith("_noise"):
                    return details.get("noise_dbm")
                return details.get("clients")
        if key.startswith("eth_") and (
            key.endswith("_speed")
            or key.endswith("_rx_bytes")
            or key.endswith("_tx_bytes")
        ):
            eth_ports = _payload(data, "ethernet_ports")
            if not isinstance(eth_ports, dict):
                return None
            for suffix, field in (
                ("_speed", "speed_mbps"),
                ("_rx_bytes", "rx_bytes"),
                ("_tx_bytes", "tx_bytes"),
            ):
                if key.endswith(suffix):
                    port_key = key[4 : -len(suffix)]
                    port = eth_ports.get(port_key)
                    return port.get(field) if isinstance(port, dict) else None
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "public_ipv4":
            wan_stats = _payload(data, "wan_stats")
            if isinstance(wan_stats, dict):
                attrs = {}
                if wan_stats.get("gateway"):
                    attrs["gateway"] = wan_stats["gateway"]
                if wan_stats.get("dns"):
                    attrs["dns"] = wan_stats["dns"]
                return attrs or None
            return None
        if key != "active_clients":
            return None
        hosts_payload = _payload(data, "hosts")
        try:
            hosts_list = hosts_payload[0]["hosts"]["list"]
        except (KeyError, IndexError, TypeError):
            return None
        if not isinstance(hosts_list, list):
            return None
        devices = [
            {
                "hostname": host.get("hostname"),
                "ip_address": host.get("ipaddress"),
                "mac_address": host.get("macaddress"),
                "interface": host.get("link"),
            }
            for host in hosts_list
            if host.get("active")
        ]
        return {"devices": devices}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom sensors."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    sensors: list[SagecomSensor] = []

    for description in SENSORS:
        candidate = SagecomSensor(coordinator, description)
        if candidate.native_value is not None:
            sensors.append(candidate)

    data = coordinator.data or {}
    optional_descriptions: list[SensorEntityDescription] = [
        SensorEntityDescription(
            key="wan_rx_bytes",
            name="WAN received",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:download-network",
        ),
        SensorEntityDescription(
            key="wan_tx_bytes",
            name="WAN transmitted",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:upload-network",
        ),
        SensorEntityDescription(
            key="wan_daily_rx_bytes",
            name="WAN daily received",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:download-network",
        ),
        SensorEntityDescription(
            key="wan_daily_tx_bytes",
            name="WAN daily transmitted",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:upload-network",
        ),
        SensorEntityDescription(
            key="wan_quarter_hour_rx_bytes",
            name="WAN 15m received",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:download-network",
        ),
        SensorEntityDescription(
            key="wan_quarter_hour_tx_bytes",
            name="WAN 15m transmitted",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:upload-network",
        ),
        SensorEntityDescription(
            key="lan_rx_bytes",
            name="LAN received",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:lan",
        ),
        SensorEntityDescription(
            key="lan_tx_bytes",
            name="LAN transmitted",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:lan",
        ),
        SensorEntityDescription(
            key="memory_usage_pct",
            name="Memory usage",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:memory",
        ),
        SensorEntityDescription(
            key="memory_free_kb",
            name="Memory free",
            native_unit_of_measurement=UnitOfInformation.KILOBYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:memory",
        ),
        SensorEntityDescription(
            key="load_1m",
            name="CPU load 1m",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cpu-64-bit",
        ),
        SensorEntityDescription(
            key="load_5m",
            name="CPU load 5m",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cpu-64-bit",
        ),
        SensorEntityDescription(
            key="load_15m",
            name="CPU load 15m",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cpu-64-bit",
        ),
        SensorEntityDescription(
            key="reboot_count",
            name="Reboot count",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:restart",
        ),
        SensorEntityDescription(
            key="optical_rx_power",
            name="Optical RX power",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:fiber-optic",
        ),
        SensorEntityDescription(
            key="optical_tx_power",
            name="Optical TX power",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:fiber-optic",
        ),
        SensorEntityDescription(
            key="optical_temperature",
            name="Optical temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:thermometer",
        ),
        SensorEntityDescription(
            key="optical_voltage",
            name="Optical voltage",
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:lightning-bolt",
        ),
        SensorEntityDescription(
            key="optical_bias_current",
            name="Optical bias current",
            native_unit_of_measurement="mA",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:current-dc",
        ),
        SensorEntityDescription(
            key="gpon_state",
            name="GPON state",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:fiber-optic",
        ),
        SensorEntityDescription(
            key="optical_alarm",
            name="Optical alarm",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:alert-circle-outline",
        ),
        SensorEntityDescription(
            key="wifi24_channel",
            name="Wi-Fi 2.4 GHz channel",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        SensorEntityDescription(
            key="wifi24_noise",
            name="Wi-Fi 2.4 GHz noise",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        SensorEntityDescription(
            key="wifi24_clients",
            name="Wi-Fi 2.4 GHz clients",
            native_unit_of_measurement="clients",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:wifi",
        ),
        SensorEntityDescription(
            key="wifi5_channel",
            name="Wi-Fi 5 GHz channel",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        SensorEntityDescription(
            key="wifi5_noise",
            name="Wi-Fi 5 GHz noise",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        SensorEntityDescription(
            key="wifi5_clients",
            name="Wi-Fi 5 GHz clients",
            native_unit_of_measurement="clients",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:wifi",
        ),
    ]

    eth_ports = _payload(data, "ethernet_ports")
    if isinstance(eth_ports, dict):
        for port_key, port in eth_ports.items():
            alias = port.get("alias") or port_key.upper()
            optional_descriptions.extend(
                [
                    SensorEntityDescription(
                        key=f"eth_{port_key}_speed",
                        name=f"Ethernet {alias} speed",
                        native_unit_of_measurement="Mbit/s",
                        state_class=SensorStateClass.MEASUREMENT,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        icon="mdi:ethernet",
                    ),
                    SensorEntityDescription(
                        key=f"eth_{port_key}_rx_bytes",
                        name=f"Ethernet {alias} received",
                        native_unit_of_measurement=UnitOfInformation.BYTES,
                        device_class=SensorDeviceClass.DATA_SIZE,
                        state_class=SensorStateClass.TOTAL_INCREASING,
                        icon="mdi:ethernet",
                    ),
                    SensorEntityDescription(
                        key=f"eth_{port_key}_tx_bytes",
                        name=f"Ethernet {alias} transmitted",
                        native_unit_of_measurement=UnitOfInformation.BYTES,
                        device_class=SensorDeviceClass.DATA_SIZE,
                        state_class=SensorStateClass.TOTAL_INCREASING,
                        icon="mdi:ethernet",
                    ),
                ]
            )

    for description in optional_descriptions:
        candidate = SagecomSensor(coordinator, description)
        if candidate.native_value is not None:
            sensors.append(candidate)

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
