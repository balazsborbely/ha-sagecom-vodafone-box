"""Device trackers for active Sagemcom hosts."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SagecomCoordinator
from .entity import SagecomEntity


def _hosts(data: dict) -> list[dict]:
    try:
        return data["hosts"][0]["hosts"]["list"]
    except (KeyError, IndexError, TypeError):
        return []


class SagecomHostTracker(SagecomEntity, ScannerEntity):
    """Track an active host seen by the router."""

    def __init__(
        self,
        coordinator: SagecomCoordinator,
        mac_address: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac_address.lower()
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.api.host}-{self._mac}"

    @property
    def is_connected(self) -> bool:
        for host in _hosts(self.coordinator.data or {}):
            if str(host.get("macaddress", "")).lower() == self._mac:
                return bool(host.get("active"))
        return False

    @property
    def ip_address(self) -> str | None:
        for host in _hosts(self.coordinator.data or {}):
            if str(host.get("macaddress", "")).lower() == self._mac:
                return host.get("ipaddress")
        return None

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def extra_state_attributes(self) -> dict:
        for host in _hosts(self.coordinator.data or {}):
            if str(host.get("macaddress", "")).lower() == self._mac:
                return {
                    "ip_address": host.get("ipaddress"),
                    "connection": host.get("link"),
                    "band": host.get("wireless", {}).get("band"),
                }
        return {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up trackers for currently active hosts."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    trackers = []
    seen: set[str] = set()
    for host in _hosts(coordinator.data or {}):
        mac_address = str(host.get("macaddress") or "").strip()
        if not host.get("active") or not mac_address or mac_address in seen:
            continue
        seen.add(mac_address)
        name = str(host.get("hostname") or mac_address)
        trackers.append(SagecomHostTracker(coordinator, mac_address, name))
    async_add_entities(trackers)
