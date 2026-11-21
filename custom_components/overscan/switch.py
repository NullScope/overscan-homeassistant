"""The switch that starts and stops sync."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    OverscanAuthError,
    OverscanConnectionError,
    OverscanError,
    OverscanRefusedError,
    OverscanScreenOffError,
    OverscanUnsupportedError,
)
from .const import DOMAIN
from .coordinator import OverscanConfigEntry
from .entity import OverscanEntity

# The TV answers one request at a time.
PARALLEL_UPDATES = 1

SYNC = SwitchEntityDescription(key="sync", translation_key="sync")


async def async_setup_entry(
    hass: HomeAssistant, entry: OverscanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the sync switch."""
    async_add_entities([OverscanSyncSwitch(entry.runtime_data, SYNC)])


class OverscanSyncSwitch(OverscanEntity, SwitchEntity):
    """On while sync is switched on, as with the TV menu's Start and Stop.

    The TV refuses to start while its screen is off; stopping always works.
    """

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_sync(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_sync(False)

    async def _set_sync(self, enabled: bool) -> None:
        client = self.coordinator.client
        try:
            await (client.start() if enabled else client.stop())
        except OverscanAuthError as err:
            # The TV forgot this device, so pairing again is the only fix.
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
        except OverscanScreenOffError as err:
            # The TV won't light the room while its screen is off; show the
            # screen state it reports now.
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="screen_off") from err
        except OverscanRefusedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="refused", translation_placeholders={"reason": str(err)}
            ) from err
        except OverscanUnsupportedError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="unsupported") from err
        except OverscanConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect", translation_placeholders={"error": str(err)}
            ) from err
        except OverscanError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed", translation_placeholders={"error": str(err)}
            ) from err
        # Show the change now; the next poll brings the state as sync connects.
        self.coordinator.async_set_updated_data(replace(self.coordinator.data, enabled=enabled))
        await self.coordinator.async_request_refresh()
