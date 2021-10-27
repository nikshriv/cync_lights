"""Platform for sensor integration."""
from __future__ import annotations

from typing import Any

# These constants are relevant to the type of entity we are using.
# See below for how they are used.
from homeassistant.components.light import (ATTR_BRIGHTNESS, COLOR_MODE_BRIGHTNESS, LightEntity)
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
    for room in hub.cync_rooms:
        light_entity = CyncRoomEntity(room)
        new_devices.append(light_entity)
    if new_devices:
        async_add_entities(new_devices)


class CyncRoomEntity(LightEntity):
    """Representation of a dummy Cover."""

    should_poll = False

    def __init__(self, room) -> None:
        """Initialize the sensor."""
        self._room = room

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._room.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._room.remove_callback(self.async_write_ha_state)

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return f"{self._room.name}_cync"

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._room.state

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this room between 0..255."""
        return round((self._room.brightness * 255.0) / 100.0)

    @property
    def name(self) -> str:
        """Return the name of the room."""
        return self._room.name

    @property
    def supported_color_modes(self) -> set[str] | None:
        """Return list of available color modes."""
        modes = set()
        modes.add(COLOR_MODE_BRIGHTNESS)
        return modes

    @property
    def color_mode(self) -> str | None:
        """Return the active color mode."""
        return COLOR_MODE_BRIGHTNESS

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light by setting brightness."""
        brightness = round((kwargs.get(ATTR_BRIGHTNESS) * 100) / 255)
        await self._room.turn_on(brightness)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._room.turn_off()