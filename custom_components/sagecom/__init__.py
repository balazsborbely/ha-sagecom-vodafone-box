"""The Sagemcom Vodafone integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import SagecomApi
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import SagecomCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sagemcom Vodafone from a config entry."""
    api = SagecomApi(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    await api.async_login()

    coordinator = SagecomCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Sagemcom Vodafone config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["api"].async_close()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when an entry is updated."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register explicit router management services."""

    def api_for_call(call) -> tuple[SagecomApi, object]:
        entry_id = call.data.get("entry_id")
        if entry_id:
            data = hass.data[DOMAIN][entry_id]
        else:
            data = next(iter(hass.data[DOMAIN].values()))
        return data["api"], data["coordinator"]

    async def reboot(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_reboot()
        await coordinator.async_request_refresh()

    async def reset_wifi(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_reset_wifi()
        await coordinator.async_request_refresh()

    async def set_dhcp_reservation(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_dhcp_reservation(
            hostname=call.data["hostname"],
            mac_address=call.data["mac_address"],
            ip_address=call.data["ip_address"],
            reservation_id=call.data.get("reservation_id"),
        )
        await coordinator.async_request_refresh()

    async def delete_dhcp_reservation(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_delete_dhcp_reservation(call.data["reservation_id"])
        await coordinator.async_request_refresh()

    async def set_port_forward(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_port_forward(
            rule_id=call.data.get("rule_id"),
            description=call.data["description"],
            protocol=call.data["protocol"],
            external_ip=call.data.get("external_ip", "0.0.0.0"),
            external_port=call.data["external_port"],
            internal_ip=call.data["internal_ip"],
            internal_port=call.data["internal_port"],
            enabled=call.data.get("enabled", True),
        )
        await coordinator.async_request_refresh()

    async def delete_port_forward(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_delete_port_forward(call.data["rule_id"])
        await coordinator.async_request_refresh()

    async def set_firewall_rule(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_firewall_rule(
            rule_id=call.data.get("rule_id"),
            description=call.data["description"],
            action=call.data["action"],
            destination_ip=call.data.get("destination_ip", "0.0.0.0"),
            destination_ports=call.data.get("destination_ports", "-1"),
            source_ip=call.data.get("source_ip", "0.0.0.0"),
            source_ports=call.data.get("source_ports", "-1"),
            ip_protocol=call.data.get("ip_protocol", "TCP"),
            enabled=call.data.get("enabled", True),
        )
        await coordinator.async_request_refresh()

    async def delete_firewall_rule(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_delete_firewall_rule(call.data["rule_id"])
        await coordinator.async_request_refresh()

    async def set_parental_control(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_parental_control(call.data["mac_address"])
        await coordinator.async_request_refresh()

    async def delete_parental_control(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_parental_control(
            call.data["mac_address"],
            remove=True,
            rule_id=call.data["rule_id"],
        )
        await coordinator.async_request_refresh()

    async def set_url_filter(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_url_filter(call.data["enabled"])
        await coordinator.async_request_refresh()

    async def set_upnp(call) -> None:
        api, coordinator = api_for_call(call)
        await api.async_set_upnp(call.data["enabled"])
        await coordinator.async_request_refresh()

    common = {vol.Optional("entry_id"): str}
    services = (
        ("reboot", reboot, common),
        ("reset_wifi", reset_wifi, common),
        (
            "set_dhcp_reservation",
            set_dhcp_reservation,
            common
            | {
                vol.Required("hostname"): str,
                vol.Required("mac_address"): str,
                vol.Required("ip_address"): str,
                vol.Optional("reservation_id"): int,
            },
        ),
        (
            "delete_dhcp_reservation",
            delete_dhcp_reservation,
            common | {vol.Required("reservation_id"): int},
        ),
        (
            "set_port_forward",
            set_port_forward,
            common
            | {
                vol.Optional("rule_id"): int,
                vol.Required("description"): str,
                vol.Required("protocol"): str,
                vol.Optional("external_ip", default="0.0.0.0"): str,
                vol.Required("external_port"): str,
                vol.Required("internal_ip"): str,
                vol.Required("internal_port"): str,
                vol.Optional("enabled", default=True): bool,
            },
        ),
        (
            "delete_port_forward",
            delete_port_forward,
            common | {vol.Required("rule_id"): int},
        ),
        (
            "set_firewall_rule",
            set_firewall_rule,
            common
            | {
                vol.Optional("rule_id"): int,
                vol.Required("description"): str,
                vol.Required("action"): str,
                vol.Optional("destination_ip", default="0.0.0.0"): str,
                vol.Optional("destination_ports", default="-1"): str,
                vol.Optional("source_ip", default="0.0.0.0"): str,
                vol.Optional("source_ports", default="-1"): str,
                vol.Optional("ip_protocol", default="TCP"): str,
                vol.Optional("enabled", default=True): bool,
            },
        ),
        (
            "delete_firewall_rule",
            delete_firewall_rule,
            common | {vol.Required("rule_id"): int},
        ),
        (
            "set_parental_control",
            set_parental_control,
            common | {vol.Required("mac_address"): str},
        ),
        (
            "delete_parental_control",
            delete_parental_control,
            common
            | {
                vol.Required("mac_address"): str,
                vol.Required("rule_id"): int,
            },
        ),
        (
            "set_url_filter",
            set_url_filter,
            common | {vol.Required("enabled"): bool},
        ),
        (
            "set_upnp",
            set_upnp,
            common | {vol.Required("enabled"): bool},
        ),
    )

    for service_name, handler, schema in services:
        if not hass.services.has_service(DOMAIN, service_name):
            hass.services.async_register(
                DOMAIN,
                service_name,
                handler,
                schema=vol.Schema(schema),
            )
