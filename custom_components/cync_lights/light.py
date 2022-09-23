"""Platform for light integration."""
from __future__ import annotations
from typing import Any, Tuple
from homeassistant.components.light import (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP, ATTR_RGB_COLOR, ColorMode, LightEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
import logging
import math

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    hub = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = []
    for room in hub.cync_rooms:
        if not hub.cync_rooms[room]._update_callback and room in config_entry.options["rooms"]:
            new_devices.append(CyncRoomEntity(hub.cync_rooms[room],hub))

    for switch_id in hub.cync_switches:
        if not hub.cync_switches[switch_id]._update_callback and not hub.cync_switches[switch_id].plug and switch_id in config_entry.options["switches"]:
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
        self.mixed_mode = False in [self.cync_hub.cync_switches[switch_id].support_brightness for switch_id in self.room.switches.keys()] and True in [self.cync_hub.cync_switches[switch_id].support_brightness for switch_id in self.room.switches.keys()]

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.room.register(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.room.reset()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers = {(DOMAIN, f"{self.room.name} ({self.room.home_name})")},
            manufacturer = "Cync by Savant",
            name = f"{self.room.name} ({self.room.home_name})",
        )

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

    def _turn_on_support_brightness(self, attr_rgb, attr_br, attr_ct, dev):
        if attr_rgb is not None and attr_br is not None:
            if math.isclose(attr_br, max([dev.rgb['r'],dev.rgb['g'],dev.rgb['b']])*dev.brightness/100, abs_tol = 2):
                self.cync_hub.combo_control(dev.brightness, 254, rgb, dev.controller, dev.mesh_id)
            else:
                self.cync_hub.combo_control(round(attr_br*100/255), 255, [255,255,255], dev.controller, dev.mesh_id)
        elif attr_rgb is None and attr_ct is None and attr_br is not None:
            if self.color_mode == ColorMode.RGB or self.color_mode == ColorMode.COLOR_TEMP:
                self.cync_hub.combo_control(round(attr_br*100/255), 255, [255,255,255], dev.controller, dev.mesh_id)
            else:
                self.cync_hub.set_brightness(round(attr_br*100/255), dev.controller, dev.mesh_id)
        elif attr_rgb is not None and attr_br is None:
            self.cync_hub.combo_control(dev.brightness, 254, attr_rgb, dev.controller, dev.mesh_id)
        elif attr_ct is not None:
            ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
            self.cync_hub.set_color_temp(ct, dev.controller, dev.mesh_id)
        else:
            self.cync_hub.turn_on_support_brightness(dev.controller, dev.mesh_id)

    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        attr_rgb = kwargs.get(ATTR_RGB_COLOR)
        attr_br = kwargs.get(ATTR_BRIGHTNESS)
        attr_ct = kwargs.get(ATTR_COLOR_TEMP)
        if not self.mixed_mode and self.room.support_brightness:
            self._turn_on_support_brightness(attr_rgb, attr_br, attr_ct, self.room)
        elif self.mixed_mode and self.room.support_brightness:
            for device_id in self.room.switches.keys():
                if (dev := self.cync_hub.cync_switches.get(device_id)) is not None:
                    if dev.support_brightness:
                        self._turn_on_support_brightness(attr_rgb, attr_br, attr_ct, dev)
                    else:
                        self.cync_hub.turn_on(dev.controller, dev.mesh_id)
        elif not self.mixed_mode and not self.room.support_brightness:
            self.cync_hub.turn_on(self.room.controller, self.room.mesh_id)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        if not self.mixed_mode and self.room.support_brightness:
            self.cync_hub.turn_off_support_brightness(self.room.controller, self.room.mesh_id)
        elif self.mixed_mode and self.room.support_brightness:
            for device_id in self.room.switches.keys():
                if (dev := self.cync_hub.cync_switches.get(device_id)) is not None:
                    if dev.support_brightness:
                        self.cync_hub.turn_off_support_brightness(dev.controller, dev.mesh_id)
                    else:
                        self.cync_hub.turn_off(dev.controller, dev.mesh_id)                
        elif not self.mixed_mode and not self.room.support_brightness:
            self.cync_hub.turn_off(self.room.controller, self.room.mesh_id)

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
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers = {(DOMAIN, f"{self.cync_switch.room.name} ({self.cync_switch.home_name})")},
            manufacturer = "Cync by Savant",
            name = f"{self.cync_switch.room.name} ({self.cync_switch.home_name})",
        )

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

    def _turn_on_support_brightness(self, attr_rgb, attr_br, attr_ct, dev):
        if attr_rgb is not None and attr_br is not None:
            if math.isclose(attr_br, max([dev.rgb['r'],dev.rgb['g'],dev.rgb['b']])*dev.brightness/100, abs_tol = 2):
                self.cync_hub.combo_control(dev.brightness, 254, rgb, dev.controller, dev.mesh_id)
            else:
                self.cync_hub.combo_control(round(attr_br*100/255), 255, [255,255,255], dev.controller, dev.mesh_id)
        elif attr_rgb is None and attr_ct is None and attr_br is not None:
            if self.color_mode == ColorMode.RGB or self.color_mode == ColorMode.COLOR_TEMP:
                self.cync_hub.combo_control(round(attr_br*100/255), 255, [255,255,255], dev.controller, dev.mesh_id)
            else:
                self.cync_hub.set_brightness(round(attr_br*100/255), dev.controller, dev.mesh_id)
        elif attr_rgb is not None and attr_br is None:
            self.cync_hub.combo_control(dev.brightness, 254, attr_rgb, dev.controller, dev.mesh_id)
        elif attr_ct is not None:
            ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
            self.cync_hub.set_color_temp(ct, dev.controller, dev.mesh_id)
        else:
            self.cync_hub.turn_on_support_brightness(dev.controller, dev.mesh_id)
            
    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        attr_rgb = kwargs.get(ATTR_RGB_COLOR)
        attr_br = kwargs.get(ATTR_BRIGHTNESS)
        attr_ct = kwargs.get(ATTR_COLOR_TEMP)
        if self.cync_switch.support_brightness:
            self._turn_on_support_brightness(attr_rgb, attr_br, attr_ct, self.cync_switch)
        else:
            self.cync_hub.turn_on(self.cync_switch.controller, self.cync_switch.mesh_id)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        if self.cync_switch.support_brightness:
            self.cync_hub.turn_off_support_brightness(self.cync_switch.controller, self.cync_switch.mesh_id)
        else:
            self.cync_hub.turn_off(self.cync_switch.controller, self.cync_switch.mesh_id)