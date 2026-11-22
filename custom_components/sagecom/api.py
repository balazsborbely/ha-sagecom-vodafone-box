"""Sagemcom XMO REST API client."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Any

from aiohttp import ClientSession, ClientTimeout, CookieJar
from passlib.hash import sha512_crypt


class SagecomError(Exception):
    """Base integration error."""


class SagecomAuthError(SagecomError):
    """Authentication failed."""


class SagecomEndpointError(SagecomError):
    """An endpoint is unavailable."""


def _sha512_crypt(password: str, salt: str, rounds: int = 5000) -> str:
    """Create the SHA-512 crypt string used by Sagemcom."""
    return sha512_crypt.hash(password, salt=salt, rounds=rounds)


class SagecomApi:
    """Client for the read-only Sagemcom REST API."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self._base_url = f"http://{self.host}"
        self._session = ClientSession(
            timeout=ClientTimeout(total=12),
            cookie_jar=CookieJar(unsafe=True),
        )
        self._logged_in = False

    async def async_close(self) -> None:
        """Close the HTTP session."""
        await self._session.close()

    def _cookie(self, name: str) -> str:
        for cookie in self._session.cookie_jar:
            if cookie.key == name:
                return cookie.value
        raise SagecomAuthError(f"Missing login cookie: {name}")

    def _csrf_header(self) -> dict[str, str]:
        for cookie in self._session.cookie_jar:
            if cookie.key == "Host-csrf_token":
                return {"X-Csrf-Token": cookie.value}
        return {}

    async def async_login(self) -> None:
        """Authenticate with the router."""
        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/login-params",
                data={"login": self.username},
            ) as response:
                if response.status not in (200, 201):
                    raise SagecomAuthError(
                        f"Login parameters request failed: HTTP {response.status}"
                    )

            nonce = self._cookie("nonce")
            salt = self._cookie("salt")
            crypted = _sha512_crypt(self.password, salt)
            cnonce = str(secrets.randbelow(10**19)).zfill(19)

            intermediate = hashlib.sha512(
                f"{self.username}:{nonce}:{crypted[3:]}".encode()
            ).hexdigest()
            auth_key = hashlib.sha512(
                f"{intermediate}:0:{cnonce}".encode()
            ).hexdigest()

            async with self._session.post(
                f"{self._base_url}/api/v1/login",
                data={
                    "login": self.username,
                    "auth_key": auth_key,
                    "cnonce": cnonce,
                },
            ) as response:
                if response.status not in (200, 201):
                    raise SagecomAuthError(f"Login failed: HTTP {response.status}")

            authenticated = await self.async_request("/api/v1/authenticated")
            if not authenticated or authenticated[0].get("authenticated") != "true":
                raise SagecomAuthError("Router rejected the login")
            self._logged_in = True
        except asyncio.TimeoutError as err:
            raise SagecomAuthError("Timed out connecting to the router") from err

    async def async_request(
        self, path: str, *, retry_auth: bool = True
    ) -> Any:
        """Send a read-only API request."""
        try:
            async with self._session.get(f"{self._base_url}{path}") as response:
                if response.status == 404:
                    raise SagecomEndpointError(path)
                if response.status in (401, 403, 500) and retry_auth:
                    await self.async_login()
                    return await self.async_request(path, retry_auth=False)
                if response.status >= 400:
                    raise SagecomError(
                        f"Router request failed for {path}: HTTP {response.status}"
                    )
                return await response.json()
        except asyncio.TimeoutError as err:
            raise SagecomError(f"Timed out requesting {path}") from err

    async def async_write(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        retry_auth: bool = True,
    ) -> Any:
        """Send an authenticated router configuration request."""
        headers = self._csrf_header()
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                data=data,
                headers=headers,
            ) as response:
                if response.status in (401, 403, 500) and retry_auth:
                    await self.async_login()
                    return await self.async_write(
                        method, path, data, retry_auth=False
                    )
                if response.status == 404:
                    raise SagecomEndpointError(path)
                if response.status >= 400:
                    raise SagecomError(
                        f"Router write failed for {path}: HTTP {response.status}"
                    )
                if response.content_type == "application/json":
                    return await response.json()
                return await response.text()
        except asyncio.TimeoutError as err:
            raise SagecomError(f"Timed out writing {path}") from err

    async def async_optional_request(self, path: str) -> Any | None:
        """Request an endpoint that may not exist on a particular model."""
        try:
            return await self.async_request(path)
        except SagecomEndpointError:
            return None

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch all read-only data used by the integration."""
        endpoints = {
            "device": "/api/v1/device",
            "hosts": "/api/v1/hosts",
            "dhcp_clients": "/api/v1/dhcp/clients",
            "reserved_addresses": "/api/v1/dhcp/reserved_address",
            "wan_status": "/api/v1/wan/status",
            "wan_ipv4": "/api/v1/wan/ipv4",
            "wan_ipv6": "/api/v1/wan/ipv6",
            "wireless": "/api/v1/wireless",
            "wireless24_stats": "/api/v1/wireless/24/stats",
            "wireless5_stats": "/api/v1/wireless/5/stats",
            "guest24_stats": "/api/v1/wireless/guest24/stats",
            "guest5_stats": "/api/v1/wireless/guest5/stats",
            "lan_stats": "/api/v1/lan/stats",
            "docsis_network": "/api/v1/docsis-info/network_parameters",
            "docsis_connection": "/api/v1/docsis-info/connection",
            "docsis_led": "/api/v1/docsis-led",
            "firewall_status": "/api/v1/firewall",
            "firewall_rules": "/api/v1/firewall/rules",
            "port_forwarding_rules": "/api/v1/nat/rules",
            "parental_control": "/api/v1/parental_control",
            "url_filters": "/api/v1/parental_control/url_filters",
            "upnp": "/api/v1/upnp/igd",
            "easy_mesh": "/api/v1/easymesh/meshmode",
        }

        results = await asyncio.gather(
            *(self.async_optional_request(path) for path in endpoints.values())
        )
        data = dict(zip(endpoints, results))
        data["authenticated"] = self._logged_in
        return data

    async def async_set_wifi(self, band: str, enabled: bool) -> Any:
        paths = {
            "24": "/api/v1/wireless/24",
            "5": "/api/v1/wireless/5",
            "guest24": "/api/v1/wireless/guest24",
            "guest5": "/api/v1/wireless/guest5",
        }
        return await self.async_write(
            "PUT", paths[band], {"enable": 1 if enabled else 0}
        )

    async def async_set_led(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/docsis-led/darkmode",
            {"enable": enabled},
        )

    async def async_set_easy_mesh(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/easymesh/meshmode",
            {"mesh_mode": 3 if enabled else 0},
        )

    async def async_set_firewall(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/firewall",
            {"enable": 1 if enabled else 0},
        )

    async def async_set_ping_response(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/firewall/pingrespond",
            {"enable": 1 if enabled else 0},
        )

    async def async_reboot(self) -> Any:
        return await self.async_write(
            "POST", "/api/v1/device/reboot", {}
        )

    async def async_reset_wifi(self) -> Any:
        return await self.async_write(
            "POST", "/api/v1/device/resetwifi", {}
        )

    async def async_set_dhcp_reservation(
        self,
        *,
        hostname: str,
        mac_address: str,
        ip_address: str,
        reservation_id: int | None = None,
    ) -> Any:
        data = {
            "enable": 1,
            "hostname": hostname,
            "macaddress": mac_address,
            "ipaddress": ip_address,
        }
        if reservation_id is None:
            return await self.async_write(
                "POST", "/api/v1/dhcp/clients", data
            )
        return await self.async_write(
            "PUT", f"/api/v1/dhcp/clients/{reservation_id}", data
        )

    async def async_delete_dhcp_reservation(self, reservation_id: int) -> Any:
        return await self.async_write(
            "DELETE", f"/api/v1/dhcp/clients/{reservation_id}"
        )

    async def async_set_port_forward(
        self,
        *,
        rule_id: int | None,
        description: str,
        protocol: str,
        external_ip: str,
        external_port: str,
        internal_ip: str,
        internal_port: str,
        enabled: bool,
    ) -> Any:
        ports = external_port.split("-", 1)
        data = {
            "enable": 1 if enabled else 0,
            "description": description,
            "protocol": protocol,
            "ipremote": external_ip or "0.0.0.0",
            "external_port": ports[0],
            "external_endport": ports[1] if len(ports) > 1 else ports[0],
            "ipaddress": internal_ip,
            "internal_port": internal_port,
            "service": description,
        }
        if rule_id is None:
            return await self.async_write("POST", "/api/v1/nat/rules", data)
        return await self.async_write(
            "PUT", f"/api/v1/nat/rules/{rule_id}", data
        )

    async def async_delete_port_forward(self, rule_id: int) -> Any:
        return await self.async_write(
            "DELETE", f"/api/v1/nat/rules/{rule_id}"
        )

    async def async_set_firewall_rule(
        self,
        *,
        rule_id: int | None,
        description: str,
        action: str,
        destination_ip: str = "0.0.0.0",
        destination_ports: str = "-1",
        source_ip: str = "0.0.0.0",
        source_ports: str = "-1",
        ip_protocol: str = "TCP",
        enabled: bool = True,
    ) -> Any:
        data = {
            "enable": 1 if enabled else 0,
            "action": action,
            "description": description,
            "dstip": destination_ip,
            "dstports": destination_ports,
            "srcip": source_ip,
            "srcports": source_ports,
            "ipprotocol": ip_protocol,
        }
        if rule_id is None:
            return await self.async_write(
                "POST", "/api/v1/firewall/rules", data
            )
        return await self.async_write(
            "PUT", f"/api/v1/firewall/rules/{rule_id}", data
        )

    async def async_delete_firewall_rule(self, rule_id: int) -> Any:
        return await self.async_write(
            "DELETE", f"/api/v1/firewall/rules/{rule_id}"
        )

    async def async_set_parental_control(
        self, mac_address: str, *, remove: bool = False, rule_id: int | None = None
    ) -> Any:
        if remove:
            return await self.async_write(
                "DELETE",
                f"/api/v1/parental_control/device_schedule/{rule_id or 0}",
                {},
            )
        return await self.async_write(
            "POST",
            "/api/v1/parental_control/device_schedule",
            {"MACAddress": mac_address},
        )

    async def async_set_url_filter(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/parental_control/url_filters",
            {"enable": 1 if enabled else 0},
        )

    async def async_set_upnp(self, enabled: bool) -> Any:
        return await self.async_write(
            "PUT",
            "/api/v1/upnp/igd",
            {"enable": 1 if enabled else 0},
        )
