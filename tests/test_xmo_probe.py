"""Standalone XMO JSON-RPC probe for Sagemcom routers (/cgi/json-req, SHA-512)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent


def sha512(value: str) -> str:
    return hashlib.sha512(value.encode("utf-8")).hexdigest()


class XmoProbe:
    """Minimal dependency-free XMO JSON-RPC client."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.base_url = f"http://{host}/cgi/json-req"
        self.username = username
        self.password_hash = sha512(password)
        self.session_id = "0"
        self.nonce = ""
        self.auth_token = ""
        self.req_index = 0

    def _send(self, actions: list[dict], priority: bool = False) -> dict:
        req_id = self.req_index
        self.req_index += 1
        cnonce = secrets.randbelow(4294967295)
        ha1 = sha512(f"{self.username}:{self.nonce}:{self.password_hash}")
        if not self.auth_token:
            auth_key = sha512(f"{ha1}:{req_id}:{cnonce}:JSON:/cgi/json-req")
        else:
            auth_key = self.auth_token

        payload = {
            "request": {
                "id": req_id,
                "session-id": self.session_id,
                "priority": priority,
                "actions": actions,
                "cnonce": cnonce,
                "auth-key": auth_key,
            }
        }
        data = urllib.parse.urlencode({"req": json.dumps(payload)}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def login(self) -> None:
        self.session_id = "0"
        self.nonce = ""
        self.auth_token = ""
        self.req_index = 0
        actions = [
            {
                "id": 0,
                "method": "logIn",
                "parameters": {
                    "user": self.username,
                    "persistent": "true",
                    "session-options": {
                        "nss": [
                            {"name": "gtw", "uri": "http://sagemcom.com/gateway-data"}
                        ],
                        "context-flags": {"get-content-name": True, "local-time": True},
                        "capability-depth": 2,
                        "capability-flags": {
                            "name": True,
                            "default-value": False,
                            "restriction": True,
                            "description": False,
                        },
                        "time-format": "ISO_8601",
                        "jwt-auth": "true",
                    },
                },
            }
        ]
        res = self._send(actions, priority=True)
        reply = res["reply"]
        if reply["error"]["code"] != 16777216:
            raise RuntimeError(f"Login request error: {reply['error']}")
        act = reply["actions"][0]
        if act["error"]["code"] != 16777239:
            raise RuntimeError(f"Login action error: {act['error']}")
        params = act["callbacks"][0]["parameters"]
        self.session_id = str(params["id"])
        self.nonce = str(params["nonce"])
        if reply.get("auth") and reply["auth"].get("token"):
            self.auth_token = reply["auth"]["token"]
        print(f"Login OK! session_id={self.session_id}, has_jwt={bool(self.auth_token)}")

    def logout(self) -> None:
        if self.session_id == "0":
            return
        try:
            self._send([{"id": 0, "method": "logOut"}])
            print("Logout OK!")
        finally:
            self.session_id = "0"

    def get_values(self, xpaths: list[str]) -> dict:
        actions = [
            {"id": i, "method": "getValue", "xpath": xp}
            for i, xp in enumerate(xpaths)
        ]
        res = self._send(actions, priority=False)
        out = {}
        for xp, act in zip(xpaths, res["reply"]["actions"]):
            if act["error"]["code"] == 16777239:
                out[xp] = act["callbacks"][0]["parameters"]["value"]
            else:
                out[xp] = {"_error": act["error"]}
        return out


if __name__ == "__main__":
    pw = (Path(__file__).resolve().parent / "router_password.txt").read_text(encoding="utf-8").strip()
    probe = XmoProbe("192.168.1.1", "admin", pw)
    probe.login()
    try:
        data = probe.get_values(
            [
                "Device/DeviceInfo",
                "Device/Hosts",
                "Device/WiFi",
                "Device/IP/Interfaces",
                "Device/Ethernet/Interfaces",
                "Device/Optical",
                "Device/Managers/Led",
                "Device/UPnP/Device/UPnPIGD",
            ]
        )
        for k, v in data.items():
            if isinstance(v, dict) and "_error" in v:
                print(f"  {k}: ERROR {v['_error']}")
            else:
                kind = list(v.keys()) if isinstance(v, dict) else type(v).__name__
                print(f"  {k}: OK ({kind})")
    finally:
        probe.logout()
