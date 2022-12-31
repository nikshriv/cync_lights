"""The Cync Room Lights integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .cync_hub import CyncHub

PLATFORMS: list[str] = ["light","binary_sensor","switch","fan"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cync Room Lights from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    remove_options_update_listener = entry.add_update_listener(options_update_listener)
    hub = CyncHub(entry.data, entry.options, remove_options_update_listener)
    hass.data[DOMAIN][entry.entry_id] = hub
    hub.start_tcp_client()
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True

async def options_update_listener(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.remove_options_update_listener()
    hub.disconnect()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
