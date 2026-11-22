"""Buttons for Sagemcom Vodafone."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SagecomCoordinator
from .entity import SagecomEntity


BUTTONS = (
    ButtonEntityDescription(
        key="reboot",
        name="Reboot router",
        device_class=ButtonDeviceClass.RESTART,
        icon="mdi:restart",
    ),
    ButtonEntityDescription(
        key="reset_wifi",
        name="Reset Wi-Fi",
        icon="mdi:wifi-refresh",
    ),
)


class SagecomButton(SagecomEntity, ButtonEntity):
    """A router action button."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: SagecomCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.api.host}-{description.key}"

    async def async_press(self) -> None:
        if self.entity_description.key == "reboot":
            await self.coordinator.api.async_reboot()
        else:
            await self.coordinator.api.async_reset_wifi()
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sagemcom action buttons."""
    coordinator: SagecomCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [SagecomButton(coordinator, description) for description in BUTTONS]
    )
