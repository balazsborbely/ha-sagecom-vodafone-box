"""Base entities for Sagemcom."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SagecomCoordinator


def _device_payload(data: dict) -> dict:
    try:
        return data["device"][0]["device"]
    except (KeyError, IndexError, TypeError):
        return {}


class SagecomEntity(CoordinatorEntity):
    """Base entity with router device information."""

    coordinator: SagecomCoordinator

    def __init__(self, coordinator: SagecomCoordinator) -> None:
        super().__init__(coordinator)
        device = _device_payload(coordinator.data or {})
        serial = device.get("serialnumber")
        model = device.get("modelname")
        firmware = (
            device.get("running", {}).get("version")
            or device.get("main", {}).get("version")
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial or coordinator.api.host)},
            name=model or "Sagemcom Vodafone",
            manufacturer="Sagemcom",
            model=model,
            sw_version=firmware,
            configuration_url=f"http://{coordinator.api.host}",
        )
