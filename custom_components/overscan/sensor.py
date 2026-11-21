"""State, Screen, Entertainment area and when the TV service started."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import SCREEN_STATES, OverscanStatus
from .const import SYNC_STATES
from .coordinator import OverscanConfigEntry, OverscanCoordinator
from .entity import OverscanEntity

PARALLEL_UPDATES = 0

# Uptime is whole seconds read at poll time; ignore drift smaller than this so
# the start time doesn't change on every poll.
_START_TOLERANCE = timedelta(seconds=30)


@dataclass(frozen=True, kw_only=True)
class OverscanSensorDescription(SensorEntityDescription):
    """A sensor read from /status."""

    value_fn: Callable[[OverscanStatus], str | None]


STATE = OverscanSensorDescription(
    key="state",
    translation_key="state",
    device_class=SensorDeviceClass.ENUM,
    options=SYNC_STATES,
    # A state added by a newer Overscan shows as unknown rather than failing.
    value_fn=lambda status: status.state if status.state in SYNC_STATES else None,
)
AREA = OverscanSensorDescription(
    key="area",
    translation_key="area",
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda status: status.area,
)
SCREEN = OverscanSensorDescription(
    key="screen",
    translation_key="screen",
    device_class=SensorDeviceClass.ENUM,
    options=list(SCREEN_STATES),
    # Unknown where the TV doesn't report it or Overscan predates the field.
    value_fn=lambda status: status.screen,
)
SERVICE_STARTED = SensorEntityDescription(
    key="service_started",
    translation_key="service_started",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: OverscanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            OverscanSensor(coordinator, STATE),
            OverscanSensor(coordinator, AREA),
            OverscanSensor(coordinator, SCREEN),
            OverscanServiceStartedSensor(coordinator, SERVICE_STARTED),
        ]
    )


class OverscanSensor(OverscanEntity, SensorEntity):
    """A value from /status."""

    entity_description: OverscanSensorDescription

    @property
    def native_value(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator.data)


class OverscanServiceStartedSensor(OverscanEntity, SensorEntity):
    """When the TV service last started, from its uptime."""

    def __init__(self, coordinator: OverscanCoordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description)
        self._started: datetime | None = None
        self._update_started()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_started()
        super()._handle_coordinator_update()

    def _update_started(self) -> None:
        uptime = self.coordinator.data.service_uptime_seconds if self.coordinator.data else None
        if uptime is None:
            self._started = None
            return
        started = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(microsecond=0)
        if self._started is None or abs(started - self._started) > _START_TOLERANCE:
            self._started = started

    @property
    def native_value(self) -> datetime | None:
        return self._started
