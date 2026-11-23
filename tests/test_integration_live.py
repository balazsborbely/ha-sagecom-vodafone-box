"""Live integration test against a Sagemcom F@st 5670v2 router at 192.168.1.1.

Requires ``sagemcom_api`` and ``passlib`` to be installed and a ``tests/router_password.txt``
file.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "custom_components" / "sagecom"


def _load_api_module():
    """Load custom_components.sagecom.api without requiring Home Assistant."""
    pkg_name = "custom_components"
    sub_name = "custom_components.sagecom"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(REPO_ROOT / "custom_components")]
        sys.modules[pkg_name] = pkg
    if sub_name not in sys.modules:
        sub = types.ModuleType(sub_name)
        sub.__path__ = [str(PACKAGE_DIR)]
        sys.modules[sub_name] = sub

    spec = importlib.util.spec_from_file_location(
        f"{sub_name}.api", PACKAGE_DIR / "api.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{sub_name}.api"] = module
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    sagecom_api = _load_api_module()
    from sagemcom_api.client import SagemcomClient

    host = "192.168.1.1"
    username = "admin"
    password = (Path(__file__).resolve().parent / "router_password.txt").read_text(encoding="utf-8").strip()

    # 1. Verify v1 API raises SagecomEndpointError (404) on F@st 5670v2
    v1 = sagecom_api.SagecomApi(host, username, password)
    try:
        await v1.async_login()
        raise AssertionError("Expected SagecomEndpointError for /api/v1/login-params")
    except sagecom_api.SagecomEndpointError as err:
        print("1. v1 fallback check OK:", err)
    finally:
        await v1.async_close()

    # 2. Verify encryption method detection (SHA512 first)
    probe = SagemcomClient(
        host=host, username=username, password=password, ssl=False, verify_ssl=False
    )
    try:
        method = await sagecom_api.async_detect_encryption_method(probe)
        print("2. Detected encryption method:", method)
        assert str(method) == "SHA512"
    finally:
        await probe.close()

    # 3. Verify SagecomXmoApi login, device_info, and async_get_data
    xmo = sagecom_api.SagecomXmoApi(
        host, username, password, encryption_method=method
    )
    try:
        await xmo.async_login()
        info = await xmo.async_get_device_info()
        print("3a. DeviceInfo:", info)
        assert info["modelname"] == "Fast5670AXv2"

        data = await xmo.async_get_data()
        print("3b. Authenticated:", data["authenticated"])
        print("3c. Device payload:", data["device"])
        print("3d. WAN status:", data["wan_status"])
        print("3e. Public IPv4:", data["wan_ipv4"])
        print("3f. WAN stats:", data["wan_stats"])
        print("3g. Wireless radios:", data["wireless"])
        print("3h. WiFi 2.4G stats:", data["wireless24_stats"])
        print("3i. WiFi 5G stats:", data["wireless5_stats"])
        print("3j. Guest 2.4G stats:", data["guest24_stats"])
        print("3k. Guest 5G stats:", data["guest5_stats"])
        print("3l. LED darkmode:", data["docsis_led"])
        print("3m. UPnP:", data["upnp"])
        print("3n. System stats:", data["system_stats"])
        print("3o. Optical:", data["optical"])
        print("3p. LAN stats:", data["lan_stats"])
        print("3q. WiFi details:", data["wifi_details"])
        print("3r. Band steering:", data["band_steering"])
        print("3s. Hotspot 5G:", data["hotspot5_stats"])
        print("3t. Ethernet ports:", list((data["ethernet_ports"] or {}).keys()))

        hosts_list = data["hosts"][0]["hosts"]["list"]
        active_hosts = [h for h in hosts_list if h["active"]]
        print(f"3u. Hosts: total={len(hosts_list)}, active={len(active_hosts)}")

        assert data["authenticated"] is True
        assert data["wan_status"]["status"] == "UP"
        assert data["wan_stats"]["rx_bytes"] > 0
        assert data["wan_stats"]["tx_bytes"] > 0
        assert data["system_stats"]["memory_usage_pct"] > 0
        assert data["optical"]["gpon_state"] == "OPERATIONAL"
        assert len(data["ethernet_ports"]) >= 4
        assert len(active_hosts) > 0
        print("\nALL LIVE ROUTER CHECKS PASSED!")
    finally:
        await xmo.async_close()


if __name__ == "__main__":
    asyncio.run(main())
