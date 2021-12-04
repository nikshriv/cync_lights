"""Platform for sensor integration."""
from __future__ import annotations

from typing import Any
import aiohttp

# These constants are relevant to the type of entity we are using.
# See below for how they are used.
from homeassistant.components.light import (ATTR_BRIGHTNESS, COLOR_MODE_BRIGHTNESS, LightEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from collections.abc import Mapping
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
CYNC_ADDON_INIT = "http://78b44672-cync-lights:3001/init"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = []
    for room in data['cync_room_data']['rooms']:
        light_entity = CyncRoomEntity(room)
        new_devices.append(light_entity)
    if new_devices:
        async_add_entities(new_devices)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CYNC_ADDON_INIT) as resp:
                pass
    except:
        raise CyncAddonUnavailable


class CyncRoomEntity(LightEntity):
    """Representation of Light."""

    should_poll = False

    def __init__(self, room) -> None:
        """Initialize the room."""
        self._room = room
        
    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return self._room.replace(' ','_') + "_cync"

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
    
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return extra state attributes"""
        return {"device_type":"cync"}

class CyncAddonUnavailable(HomeAssistantError):
    """Error raised when Cync Lights Addon has not been started before installing this integration"""