"""Client for the local API of the Overscan TV service.

The TV answers HTTP on port 8765:

- ``GET /status`` needs no key and reads the sync state.
- ``POST /register`` exchanges the code shown on the TV, under
  Help & details -> Home automation, and a device name for an API key.
- ``POST /start`` and ``POST /stop`` need HTTP Digest authentication
  (RFC 7616, SHA-256, qop=auth) with the name as the username and the key as
  the password, so the key never crosses the network.

This module has no Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from typing import Any

import aiohttp
from yarl import URL

DEFAULT_PORT = 8765
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
NAME_MAX_LENGTH = 64

# A nonce accepts each request counter once; a few retries cover a nonce that
# expired or a counter that arrived out of order.
_MAX_SIGN_ATTEMPTS = 3

_CHALLENGE_PARAM = re.compile(r'([A-Za-z][\w-]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))')


class OverscanError(Exception):
    """Base error; the message is safe to show."""


class OverscanConnectionError(OverscanError):
    """The TV could not be reached or did not answer in time."""


class OverscanResponseError(OverscanError):
    """Something answered, but not as the Overscan API does."""


class OverscanUnsupportedError(OverscanError):
    """The Overscan version on the TV has no pairing; it needs an update."""


class OverscanCodeError(OverscanError):
    """The pairing code is wrong, or the Home automation page is not open."""


class OverscanNameError(OverscanError):
    """The TV refused the device name."""

    def __init__(self, message: str, *, taken: bool) -> None:
        super().__init__(message)
        self.taken = taken


class OverscanAuthError(OverscanError):
    """The TV does not know this username and key, for example after Forget devices."""


class OverscanRefusedError(OverscanError):
    """Sync cannot change now: setup isn't finished, no room is chosen, or no capture."""


@dataclass(frozen=True, slots=True)
class OverscanStatus:
    """The reply to ``GET /status``."""

    state: str
    enabled: bool
    receiving: bool
    area: str | None
    version: str | None
    service_uptime_seconds: int | None
    started_seconds_after_boot: int | None
    first_launched_by: str | None
    raw: dict[str, Any]

    @classmethod
    def from_json(cls, data: Any) -> OverscanStatus:
        """Read a status reply; raise OverscanResponseError when it isn't Overscan's."""
        if not isinstance(data, dict) or data.get("app") != "Overscan" or not isinstance(data.get("state"), str):
            raise OverscanResponseError("The device did not answer like Overscan")
        return cls(
            state=data["state"],
            enabled=data.get("enabled") is True,
            receiving=data.get("receiving") is True,
            area=_text(data.get("area")),
            version=_text(data.get("version")),
            service_uptime_seconds=_whole(data.get("service_uptime_seconds")),
            started_seconds_after_boot=_whole(data.get("started_seconds_after_boot")),
            first_launched_by=_text(data.get("first_launched_by")),
            raw=data,
        )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _whole(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def normalize_code(code: str) -> str:
    """The code without spaces or dashes; the TV ignores case."""
    return re.sub(r"[\s-]", "", code).upper()


def valid_name(name: str) -> bool:
    """Whether the TV accepts ``name`` as a username: 1 to 64 printable ASCII, no ``"``, ``\\`` or ``:``."""
    return 0 < len(name) <= NAME_MAX_LENGTH and all(" " <= c <= "~" and c not in '"\\:' for c in name)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_response(
    username: str, realm: str, password: str, method: str, uri: str, nonce: str, nc: str, cnonce: str
) -> str:
    """The Digest ``response`` for SHA-256 and qop="auth" (RFC 7616 section 3.4.1)."""
    ha1 = _sha256(f"{username}:{realm}:{password}")
    ha2 = _sha256(f"{method}:{uri}")
    return _sha256(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")


def parse_challenge(header: str | None) -> dict[str, str] | None:
    """The parameters of a ``WWW-Authenticate: Digest ...`` header, names lower-cased."""
    if not header or header[:7].lower() != "digest ":
        return None
    params: dict[str, str] = {}
    for match in _CHALLENGE_PARAM.finditer(header[7:]):
        quoted = match.group(2)
        value = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else match.group(3)
        params[match.group(1).lower()] = value
    return params


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class OverscanClient:
    """Talks to one TV. Share one aiohttp session; the TV closes each connection."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_PORT,
        username: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._api_key = api_key
        self._lock = asyncio.Lock()
        # Reused between requests so most signed requests need one round trip.
        self._realm: str | None = None
        self._nonce: str | None = None
        self._nc = 0

    @property
    def host(self) -> str:
        return self._host

    async def get_status(self) -> OverscanStatus:
        """Read the sync state. Needs no key."""
        status, data, _ = await self._request("GET", "/status")
        if status != 200:
            raise OverscanResponseError(f"The TV answered /status with HTTP {status}")
        return OverscanStatus.from_json(data)

    async def register(self, code: str, name: str) -> tuple[str, str]:
        """Pair with the code shown on the TV. Returns the username and API key."""
        status, data, _ = await self._request("POST", "/register", json_body={"code": normalize_code(code), "name": name})
        message = _error_message(data)
        if status == 200:
            username, key = (data.get("username"), data.get("api_key")) if isinstance(data, dict) else (None, None)
            if not isinstance(username, str) or not isinstance(key, str) or not username or not key:
                raise OverscanResponseError("The TV's registration reply had no username or key")
            return username, key
        if status == 403:
            raise OverscanCodeError(message or "Wrong or expired code")
        if status == 400:
            raise OverscanNameError(message or "The TV refused the name", taken="already registered" in (message or ""))
        if status in (404, 405):
            raise OverscanUnsupportedError("This version of Overscan has no pairing; update it on the TV")
        raise OverscanError(message or f"The TV answered /register with HTTP {status}")

    async def start(self) -> None:
        """Turn sync on."""
        await self._set_sync("/start")

    async def stop(self) -> None:
        """Turn sync off."""
        await self._set_sync("/stop")

    async def _set_sync(self, path: str) -> None:
        if not self._username or not self._api_key:
            raise OverscanAuthError("This TV has not been paired")
        status, data = await self._signed_post(path)
        message = _error_message(data)
        if status == 200:
            return
        if status == 409:
            raise OverscanRefusedError(message or "Sync can't change now")
        if status in (404, 405):
            raise OverscanUnsupportedError("This version of Overscan can't be controlled; update it on the TV")
        raise OverscanError(message or f"The TV answered {path} with HTTP {status}")

    async def _signed_post(self, path: str) -> tuple[int, Any]:
        async with self._lock:
            for _ in range(_MAX_SIGN_ATTEMPTS):
                signed = self._nonce is not None
                headers = {"Authorization": self._authorization("POST", path)} if signed else {}
                status, data, response_headers = await self._request("POST", path, headers=headers)
                if status != 401:
                    return status, data
                challenge = parse_challenge(response_headers.get("WWW-Authenticate"))
                if (
                    challenge is None
                    or "nonce" not in challenge
                    or challenge.get("algorithm", "MD5").upper() != "SHA-256"
                    or "auth" not in challenge.get("qop", "").split(",")
                ):
                    raise OverscanResponseError("The TV asked for an unexpected kind of sign-in")
                stale = challenge.get("stale", "").lower() == "true"
                self._realm = challenge.get("realm", "")
                self._nonce = challenge["nonce"]
                self._nc = 0
                if signed and not stale:
                    # A signed request was turned down for its key, not its nonce.
                    raise OverscanAuthError(_error_message(data) or "Wrong username or API key")
            raise OverscanAuthError("The TV kept turning down the signed request")

    def _authorization(self, method: str, uri: str) -> str:
        assert self._username and self._api_key and self._nonce is not None
        self._nc += 1
        nc = f"{self._nc:08x}"
        cnonce = secrets.token_hex(16)
        realm = self._realm or ""
        response = digest_response(self._username, realm, self._api_key, method, uri, self._nonce, nc, cnonce)
        return (
            f"Digest username={_quote(self._username)}, realm={_quote(realm)}, nonce={_quote(self._nonce)}, "
            f"uri={_quote(uri)}, algorithm=SHA-256, qop=auth, nc={nc}, cnonce={_quote(cnonce)}, "
            f"response={_quote(response)}"
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any, Any]:
        url = URL.build(scheme="http", host=self._host, port=self._port, path=path)
        body = None if json_body is None else json.dumps(json_body).encode("utf-8")
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            async with self._session.request(
                method, url, headers=request_headers, data=body, timeout=REQUEST_TIMEOUT, allow_redirects=False
            ) as response:
                text = await response.text(errors="replace")
                status, response_headers = response.status, response.headers
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise OverscanConnectionError(f"Could not reach the TV at {self._host}:{self._port} ({err})") from err
        try:
            data = json.loads(text) if text else None
        except ValueError as err:
            raise OverscanResponseError("The device did not answer with JSON") from err
        return status, data, response_headers


def _error_message(data: Any) -> str | None:
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"]
    return None
