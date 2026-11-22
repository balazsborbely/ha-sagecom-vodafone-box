"""Config flow for Sagemcom Vodafone."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api import SagecomApi, SagecomAuthError, SagecomError
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_HOST,
    DEFAULT_USERNAME,
    DOMAIN,
)


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    api = SagecomApi(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await api.async_login()
        router = await api.async_request("/api/v1/device")
    except SagecomAuthError as err:
        raise InvalidAuth from err
    except SagecomError as err:
        raise CannotConnect from err
    finally:
        await api.async_close()

    device = router[0].get("device", {}) if router else {}
    serial = device.get("serialnumber")
    title = device.get("modelname") or "Sagemcom Vodafone"
    return {"serial": serial, "title": title}


class SagecomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _async_validate(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                unique_id = info["serial"] or user_input[CONF_HOST]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid authentication."""
