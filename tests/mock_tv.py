"""A stand-in for the Overscan TV service's local API, following tv/service/LocalApi.cs
and tv/core/ApiAccess.cs in the Overscan repository."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

REALM = "Overscan"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _parse(header: str | None) -> dict[str, str] | None:
    if not header or not header.lower().startswith("digest "):
        return None
    values: dict[str, str] = {}
    for m in re.finditer(r'(\w+)=(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))', header[7:]):
        values[m.group(1).lower()] = re.sub(r"\\(.)", r"\1", m.group(2)) if m.group(2) is not None else m.group(3)
    return values


class MockTv:
    """Holds the TV's state; tests change it directly."""

    def __init__(self, *, pairing: bool = True) -> None:
        self.pairing = pairing
        self.status: dict[str, Any] = {
            "app": "Overscan",
            "version": "1.2.4",
            "state": "off",
            "enabled": False,
            "receiving": False,
            "area": "Living room",
            "screen": "on",
            "service_uptime_seconds": 120,
            "started_seconds_after_boot": 72,
            "first_launched_by": "system",
        }
        self.code: str | None = "K7Q2MX"
        self.clients: dict[str, str] = {}  # name -> HA1
        self.nonces: dict[str, int] = {}  # nonce -> last nc
        self.refusal: str | None = None
        self.requests: list[tuple[str, str, bool]] = []  # method, path, had Authorization
        self.server: TestServer | None = None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/status", self._status)
        app.router.add_post("/register", self._register)
        app.router.add_post("/start", self._start)
        app.router.add_post("/stop", self._stop)
        return app

    async def start(self, port: int | None = None) -> int:
        self.server = TestServer(self.app(), host="127.0.0.1", port=port)
        await self.server.start_server()
        return self.server.port

    async def close(self) -> None:
        if self.server:
            await self.server.close()

    def forget_devices(self) -> None:
        self.clients.clear()

    def _record(self, request: web.Request) -> None:
        self.requests.append((request.method, request.path, "Authorization" in request.headers))

    async def _status(self, request: web.Request) -> web.Response:
        self._record(request)
        return web.json_response(self.status)

    async def _register(self, request: web.Request) -> web.Response:
        self._record(request)
        if not self.pairing:
            return web.json_response({"error": "not found"}, status=404)
        try:
            body = await request.json()
            code, name = body["code"], body["name"]
        except Exception:  # noqa: BLE001
            return web.json_response({"error": 'send JSON with "code" and "name"'}, status=400)
        if self.code is None or not isinstance(code, str) or code.upper() != self.code:
            return web.json_response({"error": "wrong or expired code"}, status=403)
        if not isinstance(name, str) or not 0 < len(name) <= 64 or any(c in '"\\:' or not " " <= c <= "~" for c in name):
            return web.json_response({"error": "name must be 1 to 64 printable ASCII characters"}, status=400)
        if any(existing.casefold() == name.casefold() for existing in self.clients):
            return web.json_response({"error": "a device with this name is already registered; choose another name"}, status=400)
        key = secrets.token_urlsafe(32)
        self.clients[name] = _sha(f"{name}:{REALM}:{key}")
        self.code = "NEW3PQ"
        return web.json_response({"username": name, "api_key": key})

    async def _start(self, request: web.Request) -> web.Response:
        return self._set(request, True)

    async def _stop(self, request: web.Request) -> web.Response:
        return self._set(request, False)

    def _challenge(self, stale: bool) -> str:
        nonce = secrets.token_urlsafe(18)
        self.nonces[nonce] = 0
        return f'Digest realm="{REALM}", qop="auth", algorithm=SHA-256, nonce="{nonce}"' + (", stale=true" if stale else "")

    def _set(self, request: web.Request, enabled: bool) -> web.Response:
        self._record(request)
        header = request.headers.get("Authorization")
        client, stale = self._authorize(request.method, request.raw_path, header)
        if client is None:
            return web.json_response(
                {"error": "authentication required" if header is None else "nonce expired or already used; retry" if stale else "wrong username or API key"},
                status=401,
                headers={"WWW-Authenticate": self._challenge(stale)},
            )
        if self.refusal:
            return web.json_response({"error": self.refusal}, status=409)
        # ServiceApp.SetSyncFromApi: /start needs the screen on; /stop always works.
        if enabled and self.status.get("screen") == "off":
            return web.json_response({"error": "the TV screen is off"}, status=409)
        self.status["enabled"] = enabled
        self.status["state"] = "connecting" if enabled else "off"
        return web.json_response({"enabled": enabled})

    def _authorize(self, method: str, uri: str, header: str | None) -> tuple[str | None, bool]:
        p = _parse(header)
        required = ("username", "realm", "nonce", "uri", "response", "qop", "nc", "cnonce", "algorithm")
        if p is None or any(name not in p for name in required):
            return None, False
        if (
            p["realm"] != REALM
            or p["qop"] != "auth"
            or p["uri"] != uri
            or not p["cnonce"]
            or p["algorithm"].upper() != "SHA-256"
            or not re.fullmatch(r"[0-9a-fA-F]{8}", p["nc"])
        ):
            return None, False
        ha1 = self.clients.get(p["username"])
        if ha1 is None:
            return None, False
        expected = _sha(f"{ha1}:{p['nonce']}:{p['nc']}:{p['cnonce']}:auth:{_sha(f'{method}:{uri}')}")
        if expected != p["response"].lower():
            return None, False
        count = int(p["nc"], 16)
        if p["nonce"] not in self.nonces or count <= self.nonces[p["nonce"]]:
            return None, True
        self.nonces[p["nonce"]] = count
        return p["username"], False
