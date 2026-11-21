"""Polls the TV's /status."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OverscanClient, OverscanError, OverscanStatus
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type OverscanConfigEntry = ConfigEntry[OverscanCoordinator]


class OverscanCoordinator(DataUpdateCoordinator[OverscanStatus]):
    """Reads the sync state of one TV."""

    config_entry: OverscanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OverscanConfigEntry, client: OverscanClient) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client

    async def _async_update_data(self) -> OverscanStatus:
        try:
            return await self.client.get_status()
        except OverscanError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
