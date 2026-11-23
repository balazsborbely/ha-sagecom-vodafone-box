"""Sagemcom XMO REST API client."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import secrets
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout, CookieJar
from passlib.hash import sha512_crypt
from sagemcom_api.client import SagemcomClient
from sagemcom_api.enums import EncryptionMethod
from sagemcom_api.exceptions import (
    AccessRestrictionException,
    AuthenticationException,
    BaseSagemcomException,
    InvalidSessionException,
    LoginRetryErrorException,
    LoginTimeoutException,
    MaximumSessionCountException,
    UnauthorizedException,
    UnknownPathException,
    UnsupportedHostException,
)

try:
    from sagemcom_api.exceptions import LoginConnectionException
except ImportError:  # pragma: no cover - sagemcom_api < 1.5
    LoginConnectionException = ConnectionError  # type: ignore[assignment,misc]

try:
    from sagemcom_api.enums import ApiMode
except ImportError:  # pragma: no cover - sagemcom_api < 1.5
    ApiMode = None  # type: ignore[assignment]


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
                if response.status == 404:
                    raise SagecomEndpointError(
                        f"Login parameters endpoint not found: HTTP {response.status}"
                    )
                if response.status not in (200, 201):
                    raise SagecomAuthError(
                        f"Login parameters request failed: HTTP {response.status}"
                    )

            try:
                nonce = self._cookie("nonce")
                salt = self._cookie("salt")
            except SagecomAuthError as err:
                raise SagecomEndpointError(
                    "Login parameters endpoint did not return nonce/salt cookies"
                ) from err
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


def _prepare_xmo_client(client: SagemcomClient) -> SagemcomClient:
    """Ensure legacy login resets session state and empty replies raise InvalidSessionException."""
    if type(client) is not SagemcomClient:
        return client

    original_login = client.login
    original_get_device_info = client.get_device_info
    original_get_hosts = client.get_hosts

    async def login():
        if ApiMode is None or getattr(client, "api_mode", None) != ApiMode.REST:
            client._session_id = 0  # pylint: disable=protected-access
            client._server_nonce = ""  # pylint: disable=protected-access
            client._request_id = -1  # pylint: disable=protected-access
        return await original_login()

    async def get_device_info():
        try:
            return await original_get_device_info()
        except TypeError as exception:
            raise InvalidSessionException(
                "Empty DeviceInfo response from gateway"
            ) from exception

    async def get_hosts(*args, **kwargs):
        try:
            return await original_get_hosts(*args, **kwargs)
        except TypeError as exception:
            raise InvalidSessionException(
                "Empty Hosts response from gateway"
            ) from exception

    client.login = login  # type: ignore[method-assign]
    client.get_device_info = get_device_info  # type: ignore[method-assign]
    client.get_hosts = get_hosts  # type: ignore[method-assign]
    return client


def create_xmo_client(
    *,
    host: str,
    username: str,
    password: str,
    encryption_method: EncryptionMethod,
    ssl: bool = False,
    verify_ssl: bool = False,
    session: ClientSession | None = None,
) -> tuple[SagemcomClient, ClientSession | None]:
    """Create a SagemcomClient configured for the detected API mode."""
    owned_session: ClientSession | None = None
    kwargs: dict[str, Any] = {
        "host": host,
        "username": username,
        "password": password,
        "authentication_method": encryption_method,
        "ssl": ssl,
    }
    if session is not None:
        kwargs["session"] = session
    elif encryption_method == "NONE":
        owned_session = ClientSession(
            timeout=ClientTimeout(total=12),
            cookie_jar=CookieJar(unsafe=True),
        )
        kwargs["session"] = owned_session
    else:
        kwargs["verify_ssl"] = verify_ssl

    if ApiMode is not None:
        kwargs["api_mode"] = (
            ApiMode.REST if encryption_method == "NONE" else ApiMode.LEGACY
        )

    client = SagemcomClient(**kwargs)
    return _prepare_xmo_client(client), owned_session


async def async_detect_encryption_method(
    client: SagemcomClient,
) -> EncryptionMethod | str | None:
    """Detect the router's encryption method and close the probe session."""
    if ApiMode is not None and getattr(client, "api_mode", None) is not ApiMode.AUTO:
        method = await client.get_encryption_method()
        if method is not None:
            with suppress(BaseSagemcomException):
                await client.logout()
        return method

    # Probe SHA512 before MD5 variants so routers with a 3-attempt lockout
    # (such as the Sagemcom F@st 5670) do not spend two failed attempts first,
    # and log out of the probe session before validation logs in again.
    probe_order = (
        EncryptionMethod.SHA512,
        EncryptionMethod.MD5,
        EncryptionMethod.MD5_NONCE,
    )
    for method in probe_order:
        client.authentication_method = method
        client._password_hash = client._SagemcomClient__generate_hash(  # pylint: disable=protected-access
            client.password, method
        )
        client._server_nonce = ""  # pylint: disable=protected-access
        client._session_id = 0  # pylint: disable=protected-access
        client._request_id = -1  # pylint: disable=protected-access
        try:
            await client.login()
        except (
            LoginTimeoutException,
            AuthenticationException,
            UnauthorizedException,
        ):
            continue

        if ApiMode is not None and getattr(client, "active_api_mode", None) is ApiMode.REST:
            detected: EncryptionMethod | str = getattr(
                EncryptionMethod, "NONE", "NONE"
            )
        else:
            detected = method
        with suppress(BaseSagemcomException):
            await client.logout()
        return detected

    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_up(item: dict[str, Any]) -> bool:
    return bool(item.get("enable")) and str(item.get("status", "")).upper() in (
        "UP",
        "ENABLED",
    )


class SagecomXmoApi:
    """Adapter exposing Sagemcom XMO/legacy routers via the SagecomApi interface."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        encryption_method: EncryptionMethod | str = EncryptionMethod.SHA512,
        ssl: bool = False,
        verify_ssl: bool = False,
        session: ClientSession | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.ssl = ssl
        self.verify_ssl = verify_ssl
        self.encryption_method = (
            EncryptionMethod(encryption_method)
            if encryption_method != "NONE"
            else encryption_method
        )
        self._client, self._owned_session = create_xmo_client(
            host=self.host,
            username=self.username,
            password=self.password,
            encryption_method=self.encryption_method,  # type: ignore[arg-type]
            ssl=ssl,
            verify_ssl=verify_ssl,
            session=session,
        )
        self._owns_client_session = session is None and self._owned_session is None
        self._logged_in = False

    async def async_close(self) -> None:
        """Close any HTTP session owned by this client."""
        if self._owned_session is not None:
            await self._owned_session.close()
        elif self._owns_client_session:
            await self._client.close()

    async def _async_optional_xpath(self, xpath: str) -> Any | None:
        try:
            return await self._client.get_value_by_xpath(xpath)
        except (UnknownPathException, KeyError, TypeError):
            return None

    async def async_login(self) -> None:
        """Verify credentials against the router."""
        logged_in = False
        try:
            await self._client.login()
            logged_in = True
            self._logged_in = True
        except (
            AccessRestrictionException,
            AuthenticationException,
            UnauthorizedException,
        ) as err:
            raise SagecomAuthError(str(err)) from err
        except (
            asyncio.TimeoutError,
            ClientError,
            ConnectionError,
            LoginConnectionException,
            LoginTimeoutException,
            LoginRetryErrorException,
            MaximumSessionCountException,
            UnsupportedHostException,
            InvalidSessionException,
            BaseSagemcomException,
        ) as err:
            raise SagecomError(str(err)) from err
        finally:
            if logged_in:
                with suppress(BaseSagemcomException):
                    await self._client.logout()

    async def async_get_device_info(self) -> dict[str, Any]:
        """Fetch device info for config flow validation."""
        try:
            await self._client.login()
            try:
                info = await self._client.get_device_info()
            finally:
                with suppress(BaseSagemcomException):
                    await self._client.logout()
            return {
                "serialnumber": info.serial_number or info.mac_address,
                "modelname": info.model_name or info.product_class,
                "macaddress": info.mac_address,
            }
        except (
            AccessRestrictionException,
            AuthenticationException,
            UnauthorizedException,
        ) as err:
            raise SagecomAuthError(str(err)) from err
        except (
            asyncio.TimeoutError,
            ClientError,
            ConnectionError,
            LoginConnectionException,
            LoginTimeoutException,
            LoginRetryErrorException,
            MaximumSessionCountException,
            UnsupportedHostException,
            InvalidSessionException,
            BaseSagemcomException,
        ) as err:
            raise SagecomError(str(err)) from err

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch all read-only data used by the integration."""
        try:
            await self._client.login()
            try:
                info = await self._client.get_device_info()
                hosts = await self._client.get_hosts(only_active=False)
                device_raw = await self._async_optional_xpath("Device/DeviceInfo")
                ip_interfaces = await self._async_optional_xpath("Device/IP/Interfaces")
                eth_interfaces = await self._async_optional_xpath(
                    "Device/Ethernet/Interfaces"
                )
                wifi = await self._async_optional_xpath("Device/WiFi")
                optical_raw = await self._async_optional_xpath("Device/Optical")
                led = await self._async_optional_xpath("Device/Managers/Led")
                upnp = await self._async_optional_xpath("Device/UPnP/Device/UPnPIGD")
            finally:
                with suppress(BaseSagemcomException):
                    await self._client.logout()
        except (
            AccessRestrictionException,
            AuthenticationException,
            UnauthorizedException,
        ) as err:
            raise SagecomAuthError(str(err)) from err
        except (
            asyncio.TimeoutError,
            ClientError,
            ConnectionError,
            LoginConnectionException,
            LoginTimeoutException,
            LoginRetryErrorException,
            MaximumSessionCountException,
            UnsupportedHostException,
            InvalidSessionException,
            BaseSagemcomException,
        ) as err:
            raise SagecomError(str(err)) from err

        self._logged_in = True
        version = info.software_version or info.external_firmware_version
        device_dict = {
            "serialnumber": info.serial_number or info.mac_address,
            "modelname": info.model_name or info.product_class,
            "uptime": info.up_time,
            "running": {"version": version},
            "main": {"version": version},
        }

        host_list = []
        for host in hosts:
            layer1 = str(host.layer1_interface or "")
            band = None
            if "5G" in layer1 or "RADIO5G" in layer1:
                band = "5GHz"
            elif "2G4" in layer1 or "RADIO2G4" in layer1:
                band = "2.4GHz"
            host_list.append(
                {
                    "macaddress": host.phys_address,
                    "ipaddress": host.ip_address,
                    "hostname": host.name or host.phys_address,
                    "active": bool(host.active),
                    "link": host.interface_type,
                    "wireless": {"band": band} if band else {},
                }
            )

        wan_status = None
        public_ipv4 = None
        wan_stats = None
        lan_stats = None
        if isinstance(ip_interfaces, list):
            wan_ifc = next(
                (
                    ifc
                    for ifc in ip_interfaces
                    if isinstance(ifc, dict) and ifc.get("alias") == "IP_DATA"
                ),
                None,
            )
            if wan_ifc:
                wan_status = {
                    "status": "UP" if _is_up(wan_ifc) else "DOWN"
                }
                ipv4_addrs = wan_ifc.get("i_pv4_addresses") or []
                gateway = None
                dns = None
                if isinstance(ipv4_addrs, list) and ipv4_addrs:
                    public_ipv4 = ipv4_addrs[0].get("ip_address") or None
                    gateway = ipv4_addrs[0].get("ip_gateway") or None
                    dns = ipv4_addrs[0].get("dns") or None
                stats = wan_ifc.get("stats") or {}
                rx = _to_int(stats.get("bytes_received"))
                tx = _to_int(stats.get("bytes_sent"))
                current_day = stats.get("current_day") or {}
                quarter_hour = stats.get("quarter_hour") or {}
                if rx is not None or tx is not None:
                    wan_stats = {
                        "rx_bytes": rx,
                        "tx_bytes": tx,
                        "daily_rx_bytes": _to_int(current_day.get("bytes_received")),
                        "daily_tx_bytes": _to_int(current_day.get("bytes_sent")),
                        "quarter_hour_rx_bytes": _to_int(
                            quarter_hour.get("bytes_received")
                        ),
                        "quarter_hour_tx_bytes": _to_int(
                            quarter_hour.get("bytes_sent")
                        ),
                        "gateway": gateway,
                        "dns": dns,
                    }

            lan_ifc = next(
                (
                    ifc
                    for ifc in ip_interfaces
                    if isinstance(ifc, dict) and ifc.get("alias") == "IP_BR_LAN"
                ),
                None,
            )
            if lan_ifc:
                l_stats = lan_ifc.get("stats") or {}
                l_rx = _to_int(l_stats.get("bytes_received"))
                l_tx = _to_int(l_stats.get("bytes_sent"))
                if l_rx is not None or l_tx is not None:
                    lan_stats = {"rx_bytes": l_rx, "tx_bytes": l_tx}

        system_stats = None
        dev_inner = (
            device_raw.get("device_info")
            if isinstance(device_raw, dict)
            else None
        )
        if isinstance(dev_inner, dict):
            mem = dev_inner.get("memory_status") or {}
            mem_total = _to_int(mem.get("total"))
            mem_free = _to_int(mem.get("free"))
            mem_pct = (
                round((mem_total - mem_free) / mem_total * 100.0, 1)
                if mem_total and mem_free is not None
                else None
            )
            load = (dev_inner.get("process_status") or {}).get("load_average") or {}
            system_stats = {
                "memory_total_kb": mem_total,
                "memory_free_kb": mem_free,
                "memory_usage_pct": mem_pct,
                "load_1m": round(float(load["load1"]), 2)
                if load.get("load1") is not None
                else None,
                "load_5m": round(float(load["load5"]), 2)
                if load.get("load5") is not None
                else None,
                "load_15m": round(float(load["load15"]), 2)
                if load.get("load15") is not None
                else None,
                "reboot_count": _to_int(dev_inner.get("reboot_count")),
            }

        ethernet_ports = None
        if isinstance(eth_interfaces, list) and eth_interfaces:
            ethernet_ports = {}
            for ifc in eth_interfaces:
                if not isinstance(ifc, dict):
                    continue
                alias = str(ifc.get("alias") or "").strip()
                if not alias:
                    continue
                key = alias.lower()
                e_stats = ifc.get("stats") or {}
                ethernet_ports[key] = {
                    "alias": alias,
                    "role": ifc.get("role"),
                    "up": str(ifc.get("status", "")).upper() == "UP",
                    "status": ifc.get("status"),
                    "speed_mbps": _to_int(ifc.get("current_bit_rate")),
                    "rx_bytes": _to_int(e_stats.get("bytes_received")),
                    "tx_bytes": _to_int(e_stats.get("bytes_sent")),
                }

        optical_data = None
        opt_root = (
            optical_raw.get("optical")
            if isinstance(optical_raw, dict)
            else None
        )
        if isinstance(opt_root, dict):
            opt_ifcs = opt_root.get("interfaces") or []
            opt_ifc = opt_ifcs[0] if opt_ifcs and isinstance(opt_ifcs[0], dict) else {}
            g988 = (
                opt_root.get("G988")
                or opt_root.get("g988")
                or opt_root.get("g_988")
                or {}
            )
            rx_raw = _to_int(opt_ifc.get("optical_signal_level"))
            tx_raw = _to_int(opt_ifc.get("transmit_optical_level"))
            temp_raw = _to_int(opt_ifc.get("temperature"))
            volt_raw = _to_int(opt_ifc.get("voltage"))
            bias_raw = _to_int(opt_ifc.get("bias_current"))
            optical_data = {
                "rx_power_dbm": round(rx_raw / 1000.0, 2)
                if rx_raw is not None
                else None,
                "tx_power_dbm": round(tx_raw / 1000.0, 2)
                if tx_raw is not None
                else None,
                "temperature_c": round(temp_raw / 1000.0, 1)
                if temp_raw is not None
                else None,
                "voltage_v": round(volt_raw / 1_000_000.0, 3)
                if volt_raw is not None
                else None,
                "bias_current_ma": round(bias_raw / 1000.0, 2)
                if bias_raw is not None
                else None,
                "gpon_state": g988.get("gpon_state"),
                "alarm": opt_ifc.get("alarm"),
            }

        wireless_data = None
        wifi24_stats = None
        wifi5_stats = None
        guest24_stats = None
        guest5_stats = None
        hotspot5_stats = None
        wifi_details = None
        band_steering = None
        wifi_root = wifi.get("wi_fi") if isinstance(wifi, dict) else None
        if isinstance(wifi_root, dict):
            radios = {
                r.get("alias"): r
                for r in (wifi_root.get("radios") or [])
                if isinstance(r, dict)
            }
            ssids = {
                s.get("alias"): s
                for s in (wifi_root.get("ssi_ds") or wifi_root.get("ssids") or [])
                if isinstance(s, dict)
            }
            aps = {
                a.get("alias"): a
                for a in (wifi_root.get("access_points") or [])
                if isinstance(a, dict)
            }
            radio_24 = radios.get("RADIO2G4")
            radio_5 = radios.get("RADIO5G")
            if radio_24 or radio_5:
                wireless_data = [
                    {
                        "wireless": {
                            "radio": {
                                "24": {"state": _is_up(radio_24) if radio_24 else False},
                                "5": {"state": _is_up(radio_5) if radio_5 else False},
                            }
                        }
                    }
                ]
                wifi_details = {}
                for band_key, radio, ap_alias in (
                    ("24", radio_24, "PRIV0"),
                    ("5", radio_5, "VID1"),
                ):
                    if not radio:
                        continue
                    r_stats = radio.get("stats") or {}
                    ap = aps.get(ap_alias) or {}
                    assoc = ap.get("associated_devices")
                    wifi_details[band_key] = {
                        "channel": _to_int(radio.get("channel")),
                        "bandwidth": radio.get("operating_channel_bandwidth"),
                        "noise_dbm": _to_int(r_stats.get("noise")),
                        "clients": len(assoc) if isinstance(assoc, list) else None,
                    }

            bs = wifi_root.get("band_steering")
            if isinstance(bs, dict) and "enable" in bs:
                band_steering = bool(bs.get("enable"))

            def _ssid_stats(alias: str) -> list[dict[str, Any]] | None:
                ssid = ssids.get(alias)
                if not ssid:
                    return None
                stats = ssid.get("stats") or {}
                return [
                    {
                        "wireless": {
                            "ssid": {
                                "status": _is_up(ssid),
                                "stats": {
                                    "rx": {"bytes": _to_int(stats.get("bytes_received"))},
                                    "tx": {"bytes": _to_int(stats.get("bytes_sent"))},
                                },
                            }
                        }
                    }
                ]

            wifi24_stats = _ssid_stats("WL_PRIV")
            wifi5_stats = _ssid_stats("WL_VIDEO_5G")
            guest24_stats = _ssid_stats("WL_GUEST")
            guest5_stats = _ssid_stats("WL_GUEST_5G")
            hotspot5_stats = _ssid_stats("WL_HOTSPOT5G")

        led_data = None
        if isinstance(led, dict):
            led_inner = led.get("led") if "led" in led else led
            if isinstance(led_inner, dict):
                led_entry: dict[str, Any] = {}
                if "front_led_power_saving" in led_inner:
                    led_entry["darkmode"] = bool(
                        led_inner.get("front_led_power_saving")
                    )
                if "switch_led_power_saving" in led_inner:
                    led_entry["switch_darkmode"] = bool(
                        led_inner.get("switch_led_power_saving")
                    )
                if led_entry:
                    led_data = [{"led": led_entry}]

        upnp_data = None
        upnp_val = upnp
        while isinstance(upnp_val, dict):
            if "u_pn_pigd" in upnp_val:
                upnp_val = upnp_val["u_pn_pigd"]
                break
            if "upn_pigd" in upnp_val:
                upnp_val = upnp_val["upn_pigd"]
                break
            if len(upnp_val) == 1:
                upnp_val = next(iter(upnp_val.values()))
            else:
                upnp_val = None
                break
        if isinstance(upnp_val, bool):
            upnp_data = [{"upnp": {"igd": {"enable": "1" if upnp_val else "0"}}}]

        return {
            "device": [{"device": device_dict}],
            "hosts": [{"hosts": {"list": host_list}}],
            "wan_status": wan_status,
            "wan_ipv4": [{"ip_address": public_ipv4}] if public_ipv4 else None,
            "wan_stats": wan_stats,
            "lan_stats": lan_stats,
            "system_stats": system_stats,
            "ethernet_ports": ethernet_ports,
            "optical": optical_data,
            "docsis_network": (
                [{"publicIpv4": public_ipv4}] if public_ipv4 else None
            ),
            "wireless": wireless_data,
            "wireless24_stats": wifi24_stats,
            "wireless5_stats": wifi5_stats,
            "guest24_stats": guest24_stats,
            "guest5_stats": guest5_stats,
            "hotspot5_stats": hotspot5_stats,
            "wifi_details": wifi_details,
            "band_steering": band_steering,
            "docsis_led": led_data,
            "upnp": upnp_data,
            "capabilities": {"reset_wifi": False},
            "authenticated": self._logged_in,
        }

    async def _async_set_xpath(self, xpath: str, value: str) -> Any:
        try:
            await self._client.login()
            try:
                return await self._client.set_value_by_xpath(xpath, value)
            finally:
                with suppress(BaseSagemcomException):
                    await self._client.logout()
        except UnknownPathException as err:
            raise SagecomEndpointError(xpath) from err
        except (
            AccessRestrictionException,
            AuthenticationException,
            UnauthorizedException,
        ) as err:
            raise SagecomAuthError(str(err)) from err
        except BaseSagemcomException as err:
            raise SagecomError(str(err)) from err

    async def async_set_wifi(self, band: str, enabled: bool) -> Any:
        xpaths = {
            "24": "Device/WiFi/Radios/Radio[Alias='RADIO2G4']/Enable",
            "5": "Device/WiFi/Radios/Radio[Alias='RADIO5G']/Enable",
            "guest24": "Device/WiFi/SSIDs/SSID[Alias='WL_GUEST']/Enable",
            "guest5": "Device/WiFi/SSIDs/SSID[Alias='WL_GUEST_5G']/Enable",
        }
        val = "true" if enabled else "false"
        return await self._async_set_xpath(xpaths[band], val)

    async def async_set_led(self, enabled: bool) -> Any:
        return await self._async_set_xpath(
            "Device/Managers/Led/FrontLedPowerSaving",
            "true" if enabled else "false",
        )

    async def async_set_switch_led(self, enabled: bool) -> Any:
        return await self._async_set_xpath(
            "Device/Managers/Led/SwitchLedPowerSaving",
            "true" if enabled else "false",
        )

    async def async_set_band_steering(self, enabled: bool) -> Any:
        return await self._async_set_xpath(
            "Device/WiFi/BandSteering/Enable",
            "true" if enabled else "false",
        )

    async def async_set_upnp(self, enabled: bool) -> Any:
        return await self._async_set_xpath(
            "Device/UPnP/Device/UPnPIGD",
            "true" if enabled else "false",
        )

    async def async_reboot(self) -> Any:
        try:
            await self._client.login()
            try:
                await self._client.reboot()
            except ConnectionError:
                pass
        except BaseSagemcomException as err:
            raise SagecomError(str(err)) from err

    async def async_reset_wifi(self) -> Any:
        raise SagecomEndpointError("reset_wifi is not supported on XMO routers")

    async def async_set_easy_mesh(self, enabled: bool) -> Any:
        raise SagecomEndpointError("easy_mesh is not supported on XMO routers")

    async def async_set_firewall(self, enabled: bool) -> Any:
        raise SagecomEndpointError("firewall toggle is not supported on XMO routers")

    async def async_set_ping_response(self, enabled: bool) -> Any:
        raise SagecomEndpointError("ping_response is not supported on XMO routers")

    async def async_set_dhcp_reservation(self, **kwargs: Any) -> Any:
        raise SagecomEndpointError("dhcp_reservation is not supported on XMO routers")

    async def async_delete_dhcp_reservation(self, reservation_id: int) -> Any:
        raise SagecomEndpointError("dhcp_reservation is not supported on XMO routers")

    async def async_set_port_forward(self, **kwargs: Any) -> Any:
        raise SagecomEndpointError("port_forward is not supported on XMO routers")

    async def async_delete_port_forward(self, rule_id: int) -> Any:
        raise SagecomEndpointError("port_forward is not supported on XMO routers")

    async def async_set_firewall_rule(self, **kwargs: Any) -> Any:
        raise SagecomEndpointError("firewall_rule is not supported on XMO routers")

    async def async_delete_firewall_rule(self, rule_id: int) -> Any:
        raise SagecomEndpointError("firewall_rule is not supported on XMO routers")

    async def async_set_parental_control(self, *args: Any, **kwargs: Any) -> Any:
        raise SagecomEndpointError("parental_control is not supported on XMO routers")

    async def async_set_url_filter(self, enabled: bool) -> Any:
        raise SagecomEndpointError("url_filter is not supported on XMO routers")
