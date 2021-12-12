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
CYNC_TURN_ON = "http://78b44672-cync-lights:3001/turn-on"
CYNC_SET_BRIGHTNESS = "http://78b44672-cync-lights:3001/set-brightness"
CYNC_TURN_OFF = "http://78b44672-cync-lights:3001/turn-off"
CYNC_REGISTER_ID = "http://78b44672-cync-lights:3001/init"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = []
    for room,room_data in data['cync_room_data']['rooms'].items():
        light_entity = CyncRoomEntity(room,room_data)
        new_devices.append(light_entity)
    if new_devices:
        async_add_entities(new_devices)

class CyncRoomEntity(LightEntity):
    """Representation of Light."""

    should_poll = False

    def __init__(self, room, room_data) -> None:
        """Initialize the room."""

        self._room = room
        self._room_data = room_data

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""

        self._room_data['entity_id'] = self.entity_id
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(CYNC_REGISTER_ID,json={'room':self._room,'room_data':self._room_data}) as resp:
                    pass
        except:
            raise CyncAddonUnavailable 

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        pass

    @property
    def name(self) -> str:
        """Return the name of the room."""
        return self._room     

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        id_list = self._room_data['switches'].keys() 
        uid = '-'.join(id_list)
        return uid

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
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._room_data['state']

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this room between 0..255."""
        return self._room_data['brightness']

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light  brightness."""
        self._room_data['state'] = True
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None :
            self._room_data['brightness'] = brightness
            br = round((self._room_data['brightness'] * 100) / 255)
            for sw,_ in self._room_data['switches'].items():
                self._room_data['switches'][sw]['state'] = True
                self._room_data['switches'][sw]['brightness'] = br

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(CYNC_SET_BRIGHTNESS,json={'room':self._room, 'brightness':br}) as resp:
                        pass
            except:
                raise CyncAddonUnavailable
        else:
            for sw,_ in self._room_data['switches'].items():
                self._room_data['switches'][sw]['state'] = True

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(CYNC_TURN_ON,json={'room':self._room}) as resp:
                        pass
            except:
                raise CyncAddonUnavailable            

        self.async_write_ha_state()
    

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self._room_data['state'] = False
        for sw,_ in self._room_data['switches'].items():
            self._room_data['switches'][sw]['state'] = False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(CYNC_TURN_OFF,json={'room':self._room}) as resp:
                    pass
        except:
            raise CyncAddonUnavailable

        self.async_write_ha_state()

class CyncAddonUnavailable(HomeAssistantError):
    """Error raised when Cync Lights Addon has not been started before installing this integration"""