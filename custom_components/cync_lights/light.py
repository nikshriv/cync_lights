"""Platform for light integration."""
from __future__ import annotations
from typing import Any, Tuple
from homeassistant.components.light import (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP, ATTR_RGB_COLOR, ColorMode, LightEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    hub = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = []
    for room in hub.cync_rooms:
        if not hub.cync_rooms[room]._update_callback and room in hub.options["rooms"]:
            new_devices.append(CyncRoomEntity(hub.cync_rooms[room],hub))

    for switch_id in hub.cync_switches:
        if not hub.cync_switches[switch_id]._update_callback and switch_id in hub.options["switches"]:
            new_devices.append(CyncSwitchEntity(hub.cync_switches[switch_id],hub))

    if new_devices:
        async_add_entities(new_devices)

    await hub.update_state()

class CyncRoomEntity(LightEntity):
    """Representation of a Cync Room Light Entity."""

    should_poll = False

    def __init__(self, room, hub) -> None:
        """Initialize the light."""
        self.room = room
        self.cync_hub = hub

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.room.register(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.room.reset()

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        id_list = list(self.room.switches.keys())
        uid =  'cync_room_' + '-'.join(id_list)
        return uid

    @property
    def name(self) -> str:
        """Return the name of the room."""
        return self.room.name

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self.room.power_state

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this room between 0..255."""
        return round(self.room.brightness*255/100)

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    @property
    def color_temp(self) -> int | None:
        """Return the color temperature of this light in mireds for HA."""
        return self.max_mireds - round((self.max_mireds-self.min_mireds)*self.room.color_temp/100)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the RGB color tuple of this light switch"""
        return (self.room.rgb['r'],self.room.rgb['g'],self.room.rgb['b'])

    @property
    def supported_color_modes(self) -> set[str] | None:
        """Return list of available color modes."""

        modes: set[ColorMode | str] = set()

        if self.room.support_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if self.room.support_rgb:
            modes.add(ColorMode.RGB)
        if self.room.support_brightness:
            modes.add(ColorMode.BRIGHTNESS)
        if not modes:
            modes.add(ColorMode.ONOFF)
            
        return modes

    @property
    def color_mode(self) -> str | None:
        """Return the active color mode."""

        if self.room.support_color_temp:
            if self.room.support_rgb and self.room.rgb['active']:
                return ColorMode.RGB
            else:
                return ColorMode.COLOR_TEMP
        if self.room.support_brightness:
            return ColorMode.BRIGHTNESS
        else:
            return ColorMode.ONOFF 

    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""

        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None and (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self.cync_hub.combo_control(255, 254, rgb, self.room.room_controller, self.room.mesh_id)
            self.cync_hub.combo_control(round(brightness*100/255), 255, [255,255,255], self.room.room_controller, self.room.mesh_id)
        elif kwargs.get(ATTR_RGB_COLOR) is None and kwargs.get(ATTR_COLOR_TEMP) is None and (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            if self.color_mode == ColorMode.RGB or self.color_mode == ColorMode.COLOR_TEMP:
                self.cync_hub.combo_control(round(brightness*100/255), 255, [255,255,255], self.room.room_controller, self.room.mesh_id)
            else:
                self.cync_hub.set_brightness(round(brightness*100/255), self.room.room_controller, self.room.mesh_id)
        elif (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None and kwargs.get(ATTR_BRIGHTNESS) is None:
            self.cync_hub.combo_control(255, 254, rgb, self.room.room_controller, self.room.mesh_id)
        elif (color_temp := kwargs.get(ATTR_COLOR_TEMP)) is not None:
            ct = round(100*(self.max_mireds - color_temp)/(self.max_mireds - self.min_mireds))
            self.cync_hub.set_color_temp(ct, self.room.room_controller, self.room.mesh_id)
        else:
            self.cync_hub.turn_on(self.room.room_controller, self.room.mesh_id)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self.cync_hub.turn_off(self.room.room_controller, self.room.mesh_id)

class CyncSwitchEntity(LightEntity):
    """Representation of a Cync Switch Light Entity."""

    should_poll = False

    def __init__(self, cync_switch, hub) -> None:
        """Initialize the light."""
        self.cync_switch = cync_switch
        self.cync_hub = hub

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.cync_switch.register(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.cync_switch.reset()

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return 'cync_switch_' + self.cync_switch.switch_id 

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self.cync_switch.name

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self.cync_switch.power_state

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this switch between 0..255."""
        return round(self.cync_switch.brightness*255/100)

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    @property
    def color_temp(self) -> int | None:
        """Return the color temperature of this light in mireds for HA."""
        return self.max_mireds - round((self.max_mireds-self.min_mireds)*self.cync_switch.color_temp/100)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the RGB color tuple of this light switch"""
        return (self.cync_switch.rgb['r'],self.cync_switch.rgb['g'],self.cync_switch.rgb['b'])

    @property
    def supported_color_modes(self) -> set[str] | None:
        """Return list of available color modes."""

        modes: set[ColorMode | str] = set()

        if self.cync_switch.support_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if self.cync_switch.support_rgb:
            modes.add(ColorMode.RGB)
        if self.cync_switch.support_brightness:
            modes.add(ColorMode.BRIGHTNESS)
        if not modes:
            modes.add(ColorMode.ONOFF)

        return modes

    @property
    def color_mode(self) -> str | None:
        """Return the active color mode."""

        if self.cync_switch.support_color_temp:
            if self.cync_switch.support_rgb and self.cync_switch.rgb['active']:
                return ColorMode.RGB
            else:
                return ColorMode.COLOR_TEMP
        if self.cync_switch.support_brightness:
            return ColorMode.BRIGHTNESS
        else:
            return ColorMode.ONOFF 

    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""

        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None and (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self.cync_hub.combo_control(255, 254, rgb, self.cync_switch.switch_controller, self.cync_switch.mesh_id)
            self.cync_hub.combo_control(round(brightness*100/255), 255, [255,255,255], self.cync_switch.switch_controller, self.cync_switch.mesh_id)
        elif kwargs.get(ATTR_RGB_COLOR) is None and kwargs.get(ATTR_COLOR_TEMP) is None and (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            if self.color_mode == ColorMode.RGB or self.color_mode == ColorMode.COLOR_TEMP:
                self.cync_hub.combo_control(round(brightness*100/255), 255, [255,255,255], self.cync_switch.switch_controller, self.cync_switch.mesh_id)
            else:
                self.cync_hub.set_brightness(round(brightness*100/255), self.cync_switch.switch_controller, self.cync_switch.mesh_id)
        elif (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None and kwargs.get(ATTR_BRIGHTNESS) is None:
            self.cync_hub.combo_control(255, 254, rgb, self.cync_switch.switch_controller, self.cync_switch.mesh_id)
        elif (color_temp := kwargs.get(ATTR_COLOR_TEMP)) is not None:
            ct = round(100*(self.max_mireds - color_temp)/(self.max_mireds - self.min_mireds))
            self.cync_hub.set_color_temp(ct, self.cync_switch.switch_controller, self.cync_switch.mesh_id)
        else:
            self.cync_hub.turn_on(self.cync_switch.switch_controller, self.cync_switch.mesh_id)
            
    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self.cync_hub.turn_off(self.cync_switch.switch_controller, self.cync_switch.mesh_id)