"""Config flow for Cync Room Lights integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import aiohttp
import json

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .get_user_data import (GetCyncUserData, GetGoogleCredentials)

CYNC_ADDON_SETUP = "http://78b44672-cync-lights/setup:3001"

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,       
    }
)
STEP_TWO_FACTOR_CODE = vol.Schema(
    {
        vol.Required("two_factor_code"): str,
    }
)
STEP_CLIENT_SECRET = vol.Schema(
    {
        vol.Required("client_secret"): str,
    }
)
STEP_GOOGLE_AUTH_CODE = vol.Schema(
    {
        vol.Required("google_auth_code"): str,
    }
)

async def validate_user(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input"""

    response = await hub.authenticate(user_input["username"], user_input["password"])
    if response['authorized']:
        return {'title':'cync_room_light_'+ user_input['username'],'data':{'cync_credentials': hub.auth_code}}
    else:
        if response['two_factor_code_required']:
            raise TwoFactorCodeRequired
        else:
            raise InvalidAuth

async def validate_two_factor_code(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""

    response = await hub.auth_two_factor(user_input["two_factor_code"])
    if response['authorized']:
        return {'title':'cync_lights_'+ hub.username,'data':{'cync_credentials': hub.auth_code}}
    else:
        raise InvalidAuth

async def validate_client_secret(hass: HomeAssistant, hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""

    response = await hub.get_google_auth_url(hass, json.loads(user_input["client_secret"]))
    if response['valid_client_secret']:
        return response['auth_url']
    else:
        raise InvalidClientSecret

async def validate_google_auth_code(hass: HomeAssistant, hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""
    code = user_input["google_auth_code"]
    response = await hub.get_google_credentials(hass,code)
    if response['success']:
        return json.loads(hub.google_flow.credentials.to_json())
    else:
        raise InvalidGoogleAuthCode

async def setup_cync_addon(data):
    """Sends setup data to cync lights addon"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CYNC_ADDON_SETUP, json=data) as resp:
                if resp.status == 200:
                    return
                else:
                    raise CyncAddonUnavailable
    except:
        raise CyncAddonUnavailable



class CyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync Room Lights."""

    def __init__(self):
        self.cync_hub = GetCyncUserData()
        self.google_hub = GetGoogleCredentials()
        self.data ={}
        self.auth_url = ''

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user and password for Cync account."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_user(self.cync_hub, user_input)
        except TwoFactorCodeRequired:
            return await self.async_step_two_factor_code()
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data = info
            return await self.async_step_client_secret()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_two_factor_code(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle two factor authentication for Cync account."""
        if user_input is None:
            return self.async_show_form(
                step_id="two_factor_code", data_schema=STEP_TWO_FACTOR_CODE
            )

        errors = {}

        try:
            info = await validate_two_factor_code(self.cync_hub, user_input)
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data = info
            return await self.async_step_client_secret()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_client_secret(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle google client secret."""
        if user_input is None:
            return self.async_show_form(
                step_id="client_secret", data_schema=STEP_CLIENT_SECRET
            )

        errors = {}

        try:
            self.auth_url = await validate_client_secret(self.hass, self.google_hub, user_input)
        except InvalidClientSecret:
            errors["base"] = "invalid_client_secret"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return await self.async_step_google_auth_code()

        return self.async_show_form(
            step_id="client_secret", data_schema=STEP_CLIENT_SECRET, errors=errors
        )

    async def async_step_google_auth_code(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle google auth code and create entry"""
        if user_input is None:
            return self.async_show_form(
                step_id="google_auth_code", data_schema=STEP_GOOGLE_AUTH_CODE, description_placeholders = {"auth_url":self.auth_url}
            )

        errors = {}

        try:
            credentials = await validate_google_auth_code(self.hass, self.google_hub, user_input)
        except InvalidGoogleAuthCode:
            errors["base"] = "invalid_google_auth_code"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data['data']['google_credentials'] = credentials
            self.data['data']['cync_room_data'] = await self.cync_hub.get_cync_config()
            existing_entry = await self.async_set_unique_id(self.data['title'])
            try:
                await setup_cync_addon(self.data['data'])
            except CyncAddonUnavailable:
                errors["base"] = "cync_addon_unavailable"
            else:      
                if not existing_entry:              
                    return self.async_create_entry(title=self.data["title"], data=self.data["data"])
                else:
                    self.hass.config_entries.async_update_entry(existing_entry, data=self.data['data'])
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="google_auth_code", data_schema=STEP_GOOGLE_AUTH_CODE,description_placeholders = {"auth_url":self.auth_url}, errors=errors
        )

class TwoFactorCodeRequired(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class InvalidClientSecret(HomeAssistantError):
    """Error to indicate there is invalid client secret."""

class InvalidGoogleAuthCode(HomeAssistantError):
    """Error to indicate there is invalid google authorization code."""

class CyncAddonUnavailable(HomeAssistantError):
    """Error to indicate that the cync addon did not respond."""
