"""Adding a TV: its address, then the code shown on the TV."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.overscan.api import OverscanConnectionError
from custom_components.overscan.const import CONF_API_KEY, CONF_CODE, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .mock_tv import MockTv

HOST = "127.0.0.1"


def _skip_setup():
    """Keep the created entry from connecting; the flow is what's tested here."""
    return patch("custom_components.overscan.async_setup_entry", return_value=True)


async def test_pair_with_ip_then_code(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    tv = mock_tv_default_port
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: f" {HOST} "})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "AAAAAA", CONF_NAME: "Home Assistant"}
    )
    assert result["errors"] == {CONF_CODE: "invalid_code"}

    with _skip_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CODE: "k7q 2mx", CONF_NAME: "Home Assistant"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Overscan ({HOST})"
    data = result["data"]
    assert data[CONF_HOST] == HOST
    assert data[CONF_PORT] == 8765
    assert data[CONF_USERNAME] == "Home Assistant"
    assert data[CONF_API_KEY]
    assert tv.clients.keys() == {"Home Assistant"}


async def test_name_errors(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    mock_tv_default_port.clients["Home Assistant"] = "x"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7Q2MX", CONF_NAME: "Home: Assistant"}
    )
    assert result["errors"] == {CONF_NAME: "invalid_name"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7Q2MX", CONF_NAME: "home assistant"}
    )
    assert result["errors"] == {CONF_NAME: "name_taken"}

    with _skip_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CODE: "K7Q2MX", CONF_NAME: "Home Assistant 2"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "Home Assistant 2"


async def test_cannot_connect_and_not_overscan(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(
        "custom_components.overscan.config_flow.OverscanClient.get_status",
        side_effect=OverscanConnectionError("down"),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["errors"] == {"base": "cannot_connect"}

    mock_tv_default_port.status["app"] = "Other"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["errors"] == {"base": "not_overscan"}


async def test_old_overscan_cannot_pair(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    mock_tv_default_port.pairing = False
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7Q2MX", CONF_NAME: "Home Assistant"}
    )
    assert result["errors"] == {"base": "pairing_unsupported"}


async def test_already_configured(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: HOST, CONF_PORT: 8765, CONF_USERNAME: "a", CONF_API_KEY: "b"}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_pairs_again(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: 8765, CONF_USERNAME: "Home Assistant", CONF_API_KEY: "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with _skip_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CODE: "K7Q2MX", CONF_NAME: "Home Assistant"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] != "old"
    assert mock_tv_default_port.clients.keys() == {"Home Assistant"}


async def test_reconfigure_changes_address(hass: HomeAssistant, mock_tv_default_port: MockTv) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "192.0.2.1", CONF_PORT: 8765, CONF_USERNAME: "HA", CONF_API_KEY: "key"}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with _skip_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == HOST
    assert entry.data[CONF_API_KEY] == "key"
