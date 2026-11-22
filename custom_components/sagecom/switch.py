"""Switches for Sagemcom Vodafone."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SagecomCoordinator
from .entity import SagecomEntity


SWITCHES = (
    SwitchEntityDescription(
        key="wifi24",
        name="Wi-Fi 2.4 GHz",
        icon="mdi:wifi",
    ),
    SwitchEntityDescription(
        key="wifi5",
        name="Wi-Fi 5 GHz",
        icon="mdi:wifi",
    ),
    SwitchEntityDescription(
        key="guest24",
        name="Guest Wi-Fi 2.4 GHz",
        icon="mdi:wifi",
    ),
    SwitchEntityDescription(
        key="guest5",
        name="Guest Wi-Fi 5 GHz",
        icon="mdi:wifi",
    ),
    SwitchEntityDescription(
        key="led",
        name="Router LED dark mode",
        icon="mdi:led-off",
    ),
    SwitchEntityDescription(
        key="firewall",
        name="Firewall",
        icon="mdi:firewall",
    ),
    SwitchEntityDescription(
        key="easy_mesh",
        name="EasyMesh",
        icon="mdi:mesh",
    ),
    SwitchEntityDescription(
        key="upnp",
        name="UPnP",
        icon="mdi:lan",
    ),
)


class SagecomSwitch(SagecomEntity, SwitchEntity):
    """A configurable Sagemcom setting."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: SagecomCoordinator,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.host}-{description.key}"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        key = self.entity_description.key

        if key in ("wifi24", "wifi5"):
            wireless = data.get("wireless")
            try:
                radio = wireless[0]["wireless"]["radio"]["24" if key == "wifi24" else "5"]
                return bool(radio.get("state"))
            except (KeyError, IndexError, TypeError):
                return False

        if key in ("guest24", "guest5"):
            stats_key = f"{key}_stats"
            stats = data.get(stats_key)
            try:
                return bool(stats[0]["wireless"]["ssid"]["status"])
            except (KeyError, IndexError, TypeError):
                return False

        if key == "led":
            led = data.get("docsis_led")
            try:
                darkmode = led[0]["led"]["darkmode"]
                return str(darkmode).lower() == "true"
            except (KeyError, IndexError, TypeError):
                return False

        if key == "firewall":
            firewall = data.get("firewall_status")
            try:
                payload = firewall[0]["firewall"]
                return bool(payload.get("custom_level_enable") or payload.get("level"))
            except (KeyError, IndexError, TypeError):
                return False

        if key == "easy_mesh":
            mesh = data.get("easy_mesh")
            try:
                return bool(mesh and mesh[0].get("mesh_mode"))
            except (KeyError, IndexError, TypeError):
                return False

        if key == "upnp":
            upnp = data.get("upnp")
            try:
                enabled = upnp[0]["upnp"]["igd"]["enable"]
                return str(enabled) == "1"
            except (KeyError, IndexError, TypeError):
                return False

        return False

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        api = self.coordinator.api
        key = self.entity_description.key
        if key in ("wifi24", "wifi5", "guest24", "guest5"):
            band = {
                "wifi24": "24",
                "wifi5": "5",
                "guest24": "guest24",
                "guest5": "guest5",
            }[key]
            await api.async_set_wifi(band, enabled)
        elif key == "led":
            await api.async_set_led(enabled)
        elif key == "firewall":
            await api.async_set_firewall(enabled)
        elif key == "easy_mesh":
            await api.async_set_easy_mesh(enabled)
        elif key == "upnp":
            await api.async_set_upnp(enabled)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom switches."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            SagecomSwitch(coordinator, description)
            for description in SWITCHES
        ]
    )
