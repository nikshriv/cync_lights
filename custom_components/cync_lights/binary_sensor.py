"""Platform for binary sensor integration."""
from __future__ import annotations
from typing import Any
from homeassistant.components.binary_sensor import (BinarySensorDeviceClass, BinarySensorEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    hub = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = []
    for sensor in hub.cync_motion_sensors:
        if not hub.cync_motion_sensors[sensor]._update_callback and sensor in hub.options["motion_sensors"]:
            new_devices.append(CyncMotionSensorEntity(hub.cync_motion_sensors[sensor]))

    if new_devices:
        async_add_entities(new_devices)


class CyncMotionSensorEntity(BinarySensorEntity):
    """Representation of a Cync Motion Sensor."""

    should_poll = False

    def __init__(self, motion_sensor) -> None:
        """Initialize the sensor."""
        self.motion_sensor = motion_sensor

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.motion_sensor.register(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.motion_sensor.reset()

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return 'cync_motion_sensor_' + self.motion_sensor.device_id

    @property
    def name(self) -> str:
        """Return the name of the motion_sensor."""
        return self.motion_sensor.name

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self.motion_sensor.motion

    @property
    def device_class(self) -> str | None:
        """Return the device class"""
        return BinarySensorDeviceClass.MOTION

