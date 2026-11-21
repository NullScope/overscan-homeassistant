"""Entities and the sync switch against the mock TV."""

from __future__ import annotations

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.overscan.api import OverscanClient
from custom_components.overscan.const import CONF_API_KEY, DOMAIN
from custom_components.overscan.diagnostics import async_get_config_entry_diagnostics
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .mock_tv import MockTv


async def _paired_entry(hass: HomeAssistant, tv: MockTv) -> MockConfigEntry:
    async with aiohttp.ClientSession() as session:
        username, key = await OverscanClient(session, "127.0.0.1", tv.server.port).register("K7Q2MX", "Home Assistant")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Overscan (127.0.0.1)",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: tv.server.port, CONF_USERNAME: username, CONF_API_KEY: key},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _switch(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: "switch.overscan_sync"}, blocking=True)


async def test_entities_show_status(hass: HomeAssistant, mock_tv: MockTv) -> None:
    mock_tv.status.update(state="streaming", enabled=True, receiving=True)
    entry = await _paired_entry(hass, mock_tv)
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("switch.overscan_sync").state == "on"
    assert hass.states.get("sensor.overscan_sync_state").state == "streaming"
    assert hass.states.get("binary_sensor.overscan_receiving_picture").state == "on"
    assert hass.states.get("sensor.overscan_entertainment_area").state == "Living room"
    assert hass.states.get("sensor.overscan_service_started").state not in ("unknown", "unavailable")

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unknown_state_is_unknown(hass: HomeAssistant, mock_tv: MockTv) -> None:
    mock_tv.status["state"] = "something-new"
    await _paired_entry(hass, mock_tv)
    assert hass.states.get("sensor.overscan_sync_state").state == "unknown"


async def test_switch_starts_and_stops_sync(hass: HomeAssistant, mock_tv: MockTv) -> None:
    await _paired_entry(hass, mock_tv)
    assert hass.states.get("switch.overscan_sync").state == "off"

    await _switch(hass, SERVICE_TURN_ON)
    await hass.async_block_till_done()
    assert mock_tv.status["enabled"] is True
    assert hass.states.get("switch.overscan_sync").state == "on"
    assert hass.states.get("sensor.overscan_sync_state").state == "connecting"

    await _switch(hass, SERVICE_TURN_OFF)
    await hass.async_block_till_done()
    assert mock_tv.status["enabled"] is False
    assert hass.states.get("switch.overscan_sync").state == "off"


async def test_refusal_is_reported(hass: HomeAssistant, mock_tv: MockTv) -> None:
    await _paired_entry(hass, mock_tv)
    mock_tv.refusal = "choose a room first"
    with pytest.raises(HomeAssistantError) as err:
        await _switch(hass, SERVICE_TURN_ON)
    assert err.value.translation_key == "refused"
    assert hass.states.get("switch.overscan_sync").state == "off"


async def test_forgotten_device_starts_reauth(hass: HomeAssistant, mock_tv: MockTv) -> None:
    entry = await _paired_entry(hass, mock_tv)
    mock_tv.forget_devices()
    with pytest.raises(HomeAssistantError) as err:
        await _switch(hass, SERVICE_TURN_ON)
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_unreachable_tv_retries_setup(hass: HomeAssistant, mock_tv: MockTv) -> None:
    port = mock_tv.server.port
    await mock_tv.close()
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "127.0.0.1", CONF_PORT: port, CONF_USERNAME: "HA", CONF_API_KEY: "key"}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_hide_the_key(hass: HomeAssistant, mock_tv: MockTv) -> None:
    entry = await _paired_entry(hass, mock_tv)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"][CONF_API_KEY] == "**REDACTED**"
    assert diagnostics["status"]["app"] == "Overscan"
