"""Config flow for Sagemcom F@st CPE."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sagemcom_api.client import SagemcomClient
from sagemcom_api.exceptions import (
    AccessRestrictionException,
    AuthenticationException,
    LoginRetryErrorException,
    LoginTimeoutException,
    MaximumSessionCountException,
    UnsupportedHostException,
)

try:
    from sagemcom_api.exceptions import LoginConnectionException
except ImportError:  # pragma: no cover - sagemcom_api < 1.5
    LoginConnectionException = ConnectionError  # type: ignore[assignment,misc]

from .api import (
    SagecomApi,
    SagecomAuthError,
    SagecomEndpointError,
    SagecomError,
    SagecomXmoApi,
    async_detect_encryption_method,
)
from .const import (
    API_TYPE_REST_V1,
    API_TYPE_XMO,
    CONF_API_TYPE,
    CONF_ENCRYPTION_METHOD,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_HOST,
    DEFAULT_USERNAME,
    DOMAIN,
)


async def _async_validate_v1(data: dict[str, Any]) -> dict[str, Any]:
    api = SagecomApi(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await api.async_login()
        router = await api.async_request("/api/v1/device")
    finally:
        await api.async_close()

    device = router[0].get("device", {}) if router else {}
    serial = device.get("serialnumber")
    title = device.get("modelname") or "Sagemcom F@st CPE"
    return {
        "serial": serial,
        "title": title,
        "entry_data": {**data, CONF_API_TYPE: API_TYPE_REST_V1},
    }


async def _async_validate_xmo(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    host = data[CONF_HOST]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    ssl = bool(data.get(CONF_SSL, False))
    verify_ssl = bool(data.get(CONF_VERIFY_SSL, False))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    probe_client = SagemcomClient(
        host=host,
        username=username,
        password=password,
        session=session,
        ssl=ssl,
    )
    try:
        encryption_method = await async_detect_encryption_method(probe_client)
    except AccessRestrictionException as err:
        raise InvalidAuth from err
    except AuthenticationException as err:
        raise InvalidAuth from err
    except (
        TimeoutError,
        ClientError,
        ConnectionError,
        LoginConnectionException,
        LoginTimeoutException,
        MaximumSessionCountException,
        LoginRetryErrorException,
        UnsupportedHostException,
    ) as err:
        raise CannotConnect from err

    if encryption_method is None:
        raise InvalidAuth

    xmo_api = SagecomXmoApi(
        host=host,
        username=username,
        password=password,
        encryption_method=encryption_method,
        ssl=ssl,
        verify_ssl=verify_ssl,
        session=None if str(encryption_method) == "NONE" else session,
    )
    try:
        device = await xmo_api.async_get_device_info()
    except SagecomAuthError as err:
        raise InvalidAuth from err
    except SagecomError as err:
        raise CannotConnect from err
    finally:
        await xmo_api.async_close()

    return {
        "serial": device.get("serialnumber"),
        "title": device.get("modelname") or "Sagemcom F@st",
        "entry_data": {
            **data,
            CONF_API_TYPE: API_TYPE_XMO,
            CONF_ENCRYPTION_METHOD: str(encryption_method),
            CONF_SSL: ssl,
            CONF_VERIFY_SSL: verify_ssl,
        },
    }


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _async_validate_v1(data)
    except SagecomEndpointError:
        return await _async_validate_xmo(hass, data)
    except SagecomAuthError as err:
        raise InvalidAuth from err
    except (SagecomError, ClientError, TimeoutError, ConnectionError) as err:
        raise CannotConnect from err


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
                    data=info["entry_data"],
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
