"""Platform for light integration."""
from __future__ import annotations
from typing import Any
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
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
    for switch_id in hub.cync_switches:
        if not hub.cync_switches[switch_id]._update_callback and hub.cync_switches[switch_id].fan and switch_id in config_entry.options["switches"]:
            new_devices.append(CyncFanEntity(hub.cync_switches[switch_id]))

    if new_devices:
        async_add_entities(new_devices)

class CyncFanEntity(FanEntity):
    """Representation of a Cync Fan Switch Entity."""

    should_poll = False

    def __init__(self, cync_switch) -> None:
        """Initialize the light."""
        self.cync_switch = cync_switch

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
            suggested_area = f"{self.cync_switch.room.name}",
        )

    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return 'cync_switch_' + self.cync_switch.device_id 

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self.cync_switch.name

    @property
    def supported_features(self) -> int:
        """Return true if fan is on."""
        return FanEntityFeature.SET_SPEED

    @property
    def is_on(self) -> bool | None:
        """Return true if fan is on."""
        return self.cync_switch.power_state

    @property
    def percentage(self) -> int | None:
        """Return the fan speed percentage of this switch"""
        return self.cync_switch.brightness

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return 4

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the light."""
        await self.cync_switch.turn_on(None,percentage*255/100 if percentage is not None else None,None)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.cync_switch.turn_off()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
        else:
            await self.cync_switch.turn_on(None,percentage*255/100,None)