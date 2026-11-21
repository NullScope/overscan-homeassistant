"""Base entity for Overscan."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OverscanCoordinator


class OverscanEntity(CoordinatorEntity[OverscanCoordinator]):
    """An entity of the Overscan device for one TV."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OverscanCoordinator, description: EntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Overscan",
            manufacturer="Overscan",
            model="Hue sync for Samsung Tizen TVs",
            sw_version=coordinator.data.version if coordinator.data else None,
        )
