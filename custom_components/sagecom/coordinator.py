"""Data update coordinator for Sagemcom."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SagecomApi, SagecomError
from .const import DOMAIN, UPDATE_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__package__)


class SagecomCoordinator(DataUpdateCoordinator):
    """Coordinate polling of Sagemcom data."""

    def __init__(self, hass: HomeAssistant, api: SagecomApi) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.api = api
        self._consecutive_failures = 0

    async def _async_update_data(self):
        try:
            data = await self.api.async_get_data()
            self._consecutive_failures = 0
            return data
        except SagecomError as err:
            self._consecutive_failures += 1
            if self.data is not None and self._consecutive_failures <= 2:
                _LOGGER.debug(
                    "Transient Sagemcom update error (%d/2), keeping previous data: %s",
                    self._consecutive_failures,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err
