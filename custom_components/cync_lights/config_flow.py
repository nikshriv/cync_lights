"""Config flow for Cync Room Lights integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import json

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components import http
from homeassistant.components.http.view import HomeAssistantView
from homeassistant.helpers.network import get_url

from .const import DOMAIN
from .get_user_data import (GetCyncUserData, GetGoogleCredentials)

AUTH_CALLBACK_PATH = "/auth/google/callback"
AUTH_CALLBACK_NAME = "auth:google:callback"
HEADER_FRONTEND_BASE = "HA-Frontend-Base"

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str
    }
)
STEP_TWO_FACTOR_CODE = vol.Schema(
    {
        vol.Required("two_factor_code"): str
    }
)
STEP_CLIENT_SECRET = vol.Schema(
    {
        vol.Required("client_secret"): str
    }
)
STEP_GOOGLE_AUTH_CODE = vol.Schema(
    {
        vol.Required("google_auth_code"): str
    }
)

async def validate_user(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input"""

    response = await hub.authenticate(user_input["username"], user_input["password"])
    if response['authorized']:
        return {'title':'cync_room_light_'+ user_input['username'],'data':{'cync_credentials': hub.user_credentials}}
    else:
        if response['two_factor_code_required']:
            raise TwoFactorCodeRequired
        else:
            raise InvalidAuth

async def validate_two_factor_code(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""

    response = await hub.auth_two_factor(user_input["two_factor_code"])
    if response['authorized']:
        return {'title':'cync_room_light_'+ hub.username,'data':{'cync_credentials': hub.user_credentials}}
    else:
        raise InvalidAuth

async def validate_client_secret(hass: HomeAssistant, hub, forward_url, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""

    response = hub.get_google_auth_url(json.loads(user_input["client_secret"]), forward_url)
    if response['valid_client_secret']:
        return response['auth_url']
    else:
        raise InvalidClientSecret

async def validate_google_auth_code(hass: HomeAssistant, hub, auth_response) -> dict[str, Any]:
    """Validate the two factor code"""

    response = hub.get_google_credentials(user_input["google_auth_code"], auth_response)
    if response['authorized']:
        return response['credentials']
    else:
        raise GoogleAuthFailed

class CyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync Room Lights."""

    def __init__(self):
        self.cync_hub = GetCyncUserData()
        self.google_hub = GetGoogleCredentials()
        self.data = {}
        self.auth_url = None
        self.auth_response = None

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
     
        self.hass.http.register_view(GoogleAuthorizationCallbackView)
        if (req := http.current_request.get()) is None:
            raise RuntimeError("No current request in context")
        if (hass_url := req.headers.get(HEADER_FRONTEND_BASE)) is None:
            raise RuntimeError("No header in request")
        forward_url = f"{hass_url}{AUTH_CALLBACK_PATH}?flow_id={self.flow_id}"

        if user_input is None:
            return self.async_show_form(
                step_id="client_secret", data_schema=STEP_CLIENT_SECRET
            )

        errors = {}

        try:
            self.auth_url = await validate_client_secret(self.hass, self.google_hub, forward_url, user_input)
        except InvalidClientSecret:
            errors["base"] = "invalid_client_secret"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return await self.async_step_google_web_auth()

        return self.async_show_form(
            step_id="client_secret", data_schema=STEP_CLIENT_SECRET, errors=errors
        )

    async def async_step_google_web_auth(
        self, user_input = None
    ) -> FlowResult:
        """Handle google auth code and create entry"""

        if user_input is None:
            return self.async_external_step(
                step_id="google_web_auth",
                url = self.auth_url
            )

        self.auth_response = user_input
        return self.async_external_step_done(next_step_id="complete_auth")


    async def async_step_complete_auth(
        self, user_input = None
    ) -> FlowResult:

        errors = {}

        try:
            info = await validate_google_auth_code(self.hass, self.google_hub, self.auth_response)
        except GoogleAuthFailed:
            errors["base"] = "invalid_google_auth_code"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data['google_credentials'] = info['credentials']
            self.data['cync_room_data'] = await self.cync_hub.get_cync_config()
            existing_entry = await self.async_set_unique_id(self.data['title'])
            if not existing_entry:
                return self.async_create_entry(title=self.data["title"], data=self.data["data"])

            self.hass.config_entries.async_update_entry(existing_entry, data=self.data['data'])
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

class GoogleAuthorizationCallbackView(HomeAssistantView):
    """Handle callback from external auth."""

    url = AUTH_CALLBACK_PATH
    name = AUTH_CALLBACK_NAME
    requires_auth = False

    async def get(self, request):
        """Receive authorization confirmation."""
        # pylint: disable=no-self-use
        hass = request.app["hass"]
        await hass.config_entries.flow.async_configure(
            flow_id=request.query["flow_id"], user_input=request.path_qs
        )

        return web_response.Response(
            headers={"content-type": "text/html"},
            text="<script>window.close()</script>Success! This window can be closed",
        )

class TwoFactorCodeRequired(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class InvalidClientSecret(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class GoogleAuthFailed(HomeAssistantError):
    """Error to indicate there is invalid auth."""
