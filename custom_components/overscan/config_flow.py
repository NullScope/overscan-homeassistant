"""Add an Overscan TV: its address first, then the code shown on the TV."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DEFAULT_PORT,
    OverscanClient,
    OverscanCodeError,
    OverscanConnectionError,
    OverscanError,
    OverscanNameError,
    OverscanResponseError,
    OverscanStatus,
    OverscanUnsupportedError,
    normalize_code,
    valid_name,
)
from .const import CONF_API_KEY, CONF_CODE, DEFAULT_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class OverscanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair Home Assistant with Overscan on a TV."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port = DEFAULT_PORT

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the TV's address and check that Overscan answers there."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: host})
            if await self._check_status(host, errors) is not None:
                self._host = host
                return await self.async_step_pair()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(HOST_SCHEMA, user_input),
            errors=errors,
            description_placeholders={"port": str(DEFAULT_PORT)},
        )

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the code on the TV's Home automation page and register."""
        assert self._host is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = await self._register(self._host, user_input, errors)
            if credentials is not None:
                username, api_key = credentials
                return self.async_create_entry(
                    title=f"Overscan ({self._host})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_USERNAME: username,
                        CONF_API_KEY: api_key,
                    },
                )
        return self.async_show_form(
            step_id="pair",
            data_schema=_pair_schema(user_input, DEFAULT_DEVICE_NAME),
            errors=errors,
            description_placeholders={"host": self._host},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The TV no longer accepts the key, for example after Forget devices."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pair again with a new code."""
        entry = self._get_reauth_entry()
        host = entry.data[CONF_HOST]
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = await self._register(host, user_input, errors, entry.data.get(CONF_PORT, DEFAULT_PORT))
            if credentials is not None:
                username, api_key = credentials
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_USERNAME: username, CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_pair_schema(user_input, entry.data.get(CONF_USERNAME, DEFAULT_DEVICE_NAME)),
            errors=errors,
            description_placeholders={"host": host},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the TV's address, keeping the key."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if host != entry.data[CONF_HOST]:
                self._async_abort_entries_match({CONF_HOST: host})
            if await self._check_status(host, errors, entry.data.get(CONF_PORT, DEFAULT_PORT)) is not None:
                return self.async_update_reload_and_abort(
                    entry, title=f"Overscan ({host})", data_updates={CONF_HOST: host}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                HOST_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
            description_placeholders={"port": str(DEFAULT_PORT)},
        )

    async def _check_status(self, host: str, errors: dict[str, str], port: int = DEFAULT_PORT) -> OverscanStatus | None:
        client = OverscanClient(async_get_clientsession(self.hass), host, port)
        try:
            return await client.get_status()
        except OverscanConnectionError:
            errors["base"] = "cannot_connect"
        except OverscanResponseError:
            errors["base"] = "not_overscan"
        except Exception:
            _LOGGER.exception("Unexpected error reading the status of %s", host)
            errors["base"] = "unknown"
        return None

    async def _register(
        self, host: str, user_input: dict[str, Any], errors: dict[str, str], port: int = DEFAULT_PORT
    ) -> tuple[str, str] | None:
        code = normalize_code(user_input[CONF_CODE])
        name = user_input[CONF_NAME].strip()
        if not code:
            errors[CONF_CODE] = "invalid_code"
            return None
        if not valid_name(name):
            errors[CONF_NAME] = "invalid_name"
            return None
        client = OverscanClient(async_get_clientsession(self.hass), host, port)
        try:
            return await client.register(code, name)
        except OverscanCodeError:
            errors[CONF_CODE] = "invalid_code"
        except OverscanNameError as err:
            errors[CONF_NAME] = "name_taken" if err.taken else "invalid_name"
        except OverscanUnsupportedError:
            errors["base"] = "pairing_unsupported"
        except OverscanConnectionError:
            errors["base"] = "cannot_connect"
        except OverscanResponseError:
            errors["base"] = "not_overscan"
        except OverscanError as err:
            _LOGGER.warning("The TV at %s could not register this device: %s", host, err)
            errors["base"] = "register_failed"
        except Exception:
            _LOGGER.exception("Unexpected error registering with %s", host)
            errors["base"] = "unknown"
        return None


def _pair_schema(user_input: dict[str, Any] | None, default_name: str) -> vol.Schema:
    # The code is single-use, so a failed attempt doesn't keep it in the form.
    name = (user_input or {}).get(CONF_NAME, default_name)
    return vol.Schema(
        {
            vol.Required(CONF_CODE): str,
            vol.Required(CONF_NAME, default=name): str,
        }
    )
