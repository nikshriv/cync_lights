"""Platform for light integration."""
from __future__ import annotations
from typing import Any
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
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
        if not hub.cync_switches[switch_id]._update_callback and hub.cync_switches[switch_id].plug and switch_id in config_entry.options["switches"]:
            new_devices.append(CyncPlugEntity(hub.cync_switches[switch_id]))

    if new_devices:
        async_add_entities(new_devices)

    await hub.update_state()

class CyncPlugEntity(SwitchEntity):
    """Representation of a Cync Switch Light Entity."""

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
    def device_class(self) -> str | None:
        """Return the device class"""
        return SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self.cync_switch.power_state
            
    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the outlet."""
        self.cync_switch.turn_on(None, None, None)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the outlet."""
        self.cync_switch.turn_off()