"""Whether picture colors are arriving."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OverscanConfigEntry
from .entity import OverscanEntity

PARALLEL_UPDATES = 0

RECEIVING = BinarySensorEntityDescription(key="receiving", translation_key="receiving")


async def async_setup_entry(
    hass: HomeAssistant, entry: OverscanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the binary sensor."""
    async_add_entities([OverscanReceivingSensor(entry.runtime_data, RECEIVING)])


class OverscanReceivingSensor(OverscanEntity, BinarySensorEntity):
    """On while recent picture colors are arriving from the TV's capture."""

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.receiving
