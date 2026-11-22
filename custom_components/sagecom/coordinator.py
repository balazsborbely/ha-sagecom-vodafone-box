"""Data update coordinator for Sagemcom."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SagecomApi, SagecomError
from .const import DOMAIN, UPDATE_INTERVAL_SECONDS


class SagecomCoordinator(DataUpdateCoordinator):
    """Coordinate polling of Sagemcom data."""

    def __init__(self, hass: HomeAssistant, api: SagecomApi) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__package__),
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.api = api

    async def _async_update_data(self):
        try:
            return await self.api.async_get_data()
        except SagecomError as err:
            raise UpdateFailed(str(err)) from err
