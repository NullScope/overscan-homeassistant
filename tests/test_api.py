"""The API client against RFC 7616 and the mock TV."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.overscan.api import (
    OverscanAuthError,
    OverscanClient,
    OverscanCodeError,
    OverscanConnectionError,
    OverscanNameError,
    OverscanRefusedError,
    OverscanResponseError,
    OverscanUnsupportedError,
    digest_response,
    normalize_code,
    parse_challenge,
    valid_name,
)

from .mock_tv import MockTv


def test_digest_matches_rfc7616_example() -> None:
    """RFC 7616 section 3.9.1, SHA-256."""
    assert (
        digest_response(
            "Mufasa",
            "http-auth@example.org",
            "Circle of Life",
            "GET",
            "/dir/index.html",
            "7ypf/xlj9XXwfDPEoM4URrv/xwf94BcCAzFZH4GiTo0v",
            "00000001",
            "f2/wE4q74E6zIJEtWaHKaf5wv/H5QzzpXusqGemxURZJ",
        )
        == "753927fa0e85d155564e2e272a28d1802ca10daf4496794697cf8db5856cb6c1"
    )


def test_parse_challenge_as_the_tv_sends_it() -> None:
    assert parse_challenge('Digest realm="Overscan", qop="auth", algorithm=SHA-256, nonce="a-b_c", stale=true') == {
        "realm": "Overscan",
        "qop": "auth",
        "algorithm": "SHA-256",
        "nonce": "a-b_c",
        "stale": "true",
    }
    assert parse_challenge('Basic realm="x"') is None
    assert parse_challenge(None) is None


def test_code_and_name_rules() -> None:
    assert normalize_code(" k7q-2mx ") == "K7Q2MX"
    assert valid_name("Home Assistant")
    assert not valid_name("")
    assert not valid_name("a" * 65)
    assert not valid_name("Home:Assistant")
    assert not valid_name('Home "HA"')
    assert not valid_name("Casa é")


async def test_status_register_start_stop(mock_tv: MockTv) -> None:
    async with aiohttp.ClientSession() as session:
        client = OverscanClient(session, "127.0.0.1", mock_tv.server.port)
        status = await client.get_status()
        assert (status.state, status.enabled, status.area, status.version) == ("off", False, "Living room", "1.2.4")

        with pytest.raises(OverscanCodeError):
            await client.register("WRONG1", "Home Assistant")
        username, key = await client.register("k7q2mx", "Home Assistant")
        assert username == "Home Assistant"

        paired = OverscanClient(session, "127.0.0.1", mock_tv.server.port, username, key)
        mock_tv.requests.clear()
        await paired.start()
        assert mock_tv.status["enabled"] is True
        # Challenge first, then the signed request.
        assert mock_tv.requests == [("POST", "/start", False), ("POST", "/start", True)]

        mock_tv.requests.clear()
        await paired.stop()
        assert mock_tv.status["enabled"] is False
        # The nonce is reused with the next counter: one round trip.
        assert mock_tv.requests == [("POST", "/stop", True)]


async def test_stale_nonce_is_renewed(mock_tv: MockTv) -> None:
    async with aiohttp.ClientSession() as session:
        username, key = await OverscanClient(session, "127.0.0.1", mock_tv.server.port).register("K7Q2MX", "HA")
        client = OverscanClient(session, "127.0.0.1", mock_tv.server.port, username, key)
        await client.start()
        mock_tv.nonces.clear()  # As after the TV service restarts.
        mock_tv.requests.clear()
        await client.stop()
        assert mock_tv.status["enabled"] is False
        assert mock_tv.requests == [("POST", "/stop", True), ("POST", "/stop", True)]


async def test_wrong_key_and_forgotten_device(mock_tv: MockTv) -> None:
    async with aiohttp.ClientSession() as session:
        username, key = await OverscanClient(session, "127.0.0.1", mock_tv.server.port).register("K7Q2MX", "HA")
        with pytest.raises(OverscanAuthError):
            await OverscanClient(session, "127.0.0.1", mock_tv.server.port, username, key + "x").start()

        client = OverscanClient(session, "127.0.0.1", mock_tv.server.port, username, key)
        await client.start()
        mock_tv.forget_devices()
        with pytest.raises(OverscanAuthError):
            await client.stop()
        assert mock_tv.status["enabled"] is True

        with pytest.raises(OverscanAuthError):
            await OverscanClient(session, "127.0.0.1", mock_tv.server.port).start()


async def test_refused_and_name_errors(mock_tv: MockTv) -> None:
    async with aiohttp.ClientSession() as session:
        pairing = OverscanClient(session, "127.0.0.1", mock_tv.server.port)
        username, key = await pairing.register("K7Q2MX", "HA")
        with pytest.raises(OverscanNameError) as taken:
            await pairing.register("NEW3PQ", "ha")
        assert taken.value.taken
        with pytest.raises(OverscanNameError) as invalid:
            await pairing.register("NEW3PQ", "a:b")
        assert not invalid.value.taken

        mock_tv.refusal = "choose a room first"
        with pytest.raises(OverscanRefusedError, match="choose a room first"):
            await OverscanClient(session, "127.0.0.1", mock_tv.server.port, username, key).start()


async def test_unreachable_wrong_device_and_old_version(mock_tv: MockTv) -> None:
    async with aiohttp.ClientSession() as session:
        port = mock_tv.server.port
        mock_tv.status["app"] = "Something else"
        with pytest.raises(OverscanResponseError):
            await OverscanClient(session, "127.0.0.1", port).get_status()

        mock_tv.pairing = False
        with pytest.raises(OverscanUnsupportedError):
            await OverscanClient(session, "127.0.0.1", port).register("K7Q2MX", "HA")

        await mock_tv.close()
        with pytest.raises(OverscanConnectionError):
            await OverscanClient(session, "127.0.0.1", port).get_status()
