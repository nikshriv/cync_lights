"""Config flow for Cync Room Lights integration."""
from __future__ import annotations
import logging
import voluptuous as vol
import json
import aiohttp
from typing import Any
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.components.http.view import HomeAssistantView
from google_auth_oauthlib.flow import InstalledAppFlow
from homeassistant.core import HomeAssistant
from .const import DOMAIN


API_AUTH = "https://api.gelighting.com/v2/user_auth"
API_REQUEST_CODE = "https://api.gelighting.com/v2/two_factor/email/verifycode"
API_2FACTOR_AUTH = "https://api.gelighting.com/v2/user_auth/two_factor"
API_DEVICES = "https://api.gelighting.com/v2/user/{user}/subscribe/devices"
API_DEVICE_INFO = "https://api.gelighting.com/v2/product/{product_id}/device/{device_id}/property"
AUTH_CALLBACK_PATH = "/googleauth"
AUTH_CALLBACK_NAME = "googleauth"

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

async def cync_login(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input"""

    response = await hub.authenticate(user_input["username"], user_input["password"])
    if response['authorized']:
        return {'title':'cync_room_lights_'+ user_input['username'],'data':{'cync_credentials': hub.auth_code}}
    else:
        if response['two_factor_code_required']:
            raise TwoFactorCodeRequired
        else:
            raise InvalidAuth

async def submit_two_factor_code(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the two factor code"""

    response = await hub.auth_two_factor(user_input["two_factor_code"])
    if response['authorized']:
        return {'title':'cync_lights_'+ hub.username,'data':{'cync_credentials': hub.auth_code}}
    else:
        raise InvalidAuth

async def get_google_auth_url(hass: HomeAssistant, hub, user_input: dict[str, Any], flow_id, redirect_uri) -> dict[str, Any]:
    """Validate the two factor code"""

    response = await hub.get_google_auth_url(hass, json.loads(user_input["client_secret"]), flow_id, redirect_uri)
    if response['valid_client_secret']:
        return response['auth_url']
    else:
        raise InvalidClientSecret

async def get_google_credentials(hass: HomeAssistant, hub, code) -> dict[str, Any]:
    """Validate the two factor code"""
    response = await hub.get_google_credentials(hass,code)
    if response['success']:
        return json.loads(hub.google_flow.credentials.to_json())
    else:
        raise InvalidGoogleAuth

class CyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync Room Lights."""

    def __init__(self):
        self.cync_hub = GetCyncUserData()
        self.google_hub = GetGoogleCredentials()
        self.data ={}
        self.auth_url = ''
        self.googleAuthView = None

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
            info = await cync_login(self.cync_hub, user_input)
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
            info = await submit_two_factor_code(self.cync_hub, user_input)
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
            redirect_uri = f"{get_url(self.hass, prefer_external = True)}{AUTH_CALLBACK_PATH}"
            self.googleAuthView = GoogleAuthorizationCallbackView()
            self.hass.http.register_view(self.googleAuthView)
            self.auth_url = await get_google_auth_url(self.hass, self.google_hub, user_input, self.flow_id, redirect_uri)
        except InvalidClientSecret:
            errors["base"] = "invalid_client_secret"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return await self.async_step_authorization_response()

        return self.async_show_form(
            step_id="client_secret", data_schema=STEP_CLIENT_SECRET, errors=errors
        )

    async def async_step_authorization_response(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle google authorization response and create entry"""
        if self.googleAuthView.google_auth_code == '':
            return self.async_external_step(step_id="authorization_response", url=self.auth_url)

        return self.async_external_step_done(next_step_id="finish_setup")

    async def async_step_finish_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Obtain google credentials and create entry"""

        errors = {}

        try:
            credentials = await get_google_credentials(self.hass, self.google_hub, self.googleAuthView.google_auth_code)
        except InvalidGoogleAuth:
            errors["base"] = "invalid_google_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data['data']['google_credentials'] = credentials
            self.data['data']['cync_room_data'] = await self.cync_hub.get_cync_config()
            existing_entry = await self.async_set_unique_id(self.data['title'])
            if not existing_entry:              
                return self.async_create_entry(title=self.data["title"], data=self.data["data"])
            else:
                self.hass.config_entries.async_update_entry(existing_entry, data=self.data['data'])
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")


class GoogleAuthorizationCallbackView(HomeAssistantView):
    """Handle callback from external auth."""

    url = AUTH_CALLBACK_PATH
    name = AUTH_CALLBACK_NAME
    requires_auth = False

    def __init__(self):
        self.google_auth_code = ''

    async def get(self, request):
        """Receive authorization confirmation."""
        hass = request.app["hass"]
        self.google_auth_code = request.query["code"]
        await hass.config_entries.flow.async_configure(
            flow_id=request.query["state"]
        )

        return aiohttp.web_response.Response(
            headers={"content-type": "text/html"},
            text="<script>window.close()</script>Success! This window can be closed",
        )

class GetCyncUserData:

    def __init__(self):
        self.username = ''
        self.password = ''
        self.auth_code = None
        self.user_credentials = {}
        self.room_data = {}

    async def authenticate(self,username,password):
        """Authenticate with the API and get a token."""
        self.username = username
        self.password = password
        auth_data = {'corp_id': "1007d2ad150c4000", 'email': self.username, 'password': self.password}
        async with aiohttp.ClientSession() as session:
            async with session.post(API_AUTH, json=auth_data) as resp:
                if resp.status == 200:
                    self.user_credentials = await resp.json()
                    login_code = bytearray.fromhex('13000000') + (10 + len(self.user_credentials['authorize'])).to_bytes(1,'big') + bytearray.fromhex('03') + self.user_credentials['user_id'].to_bytes(4,'big') + len(self.user_credentials['authorize']).to_bytes(2,'big') + bytearray(self.user_credentials['authorize'],'ascii') + bytearray.fromhex('0000b4')
                    self.auth_code = [int.from_bytes([byt],'big') for byt in login_code]
                    return {'authorized':True}
                elif resp.status == 400:
                    request_code_data = {'corp_id': "1007d2ad150c4000", 'email': self.username, 'local_lang': "en-us"}
                    async with aiohttp.ClientSession() as session:
                        async with session.post(API_REQUEST_CODE,json=request_code_data) as resp:
                            if resp.status == 200:                    
                                return {'authorized':False,'two_factor_code_required':True}
                            else:
                                return {'authorized':False,'two_factor_code_required':False}
                else:
                    return {'authorized':False,'two_factor_code_required':False}

    async def auth_two_factor(self, code):
        """Authenticate with 2 Factor Code."""
        two_factor_data = {'corp_id': "1007d2ad150c4000", 'email': self.username,'password': self.password, 'two_factor': code, 'resource':"abcdefghijklmnop"}
        async with aiohttp.ClientSession() as session:
            async with session.post(API_2FACTOR_AUTH,json=two_factor_data) as resp:
                if resp.status == 200:
                    self.user_credentials = await resp.json()
                    login_code = bytearray.fromhex('13000000') + (10 + len(self.user_credentials['authorize'])).to_bytes(1,'big') + bytearray.fromhex('03') + self.user_credentials['user_id'].to_bytes(4,'big') + len(self.user_credentials['authorize']).to_bytes(2,'big') + bytearray(self.user_credentials['authorize'],'ascii') + bytearray.fromhex('0000b4')
                    self.auth_code = [int.from_bytes([byt],'big') for byt in login_code]
                    return {'authorized':True}
                else:
                    return {'authorized':False}

    async def get_cync_config(self):
        devices = await self._get_devices()
        rooms = []
        switch_rooms_list =[]
        home_hubs = []
        for device in devices:
            device_info = await self._get_properties(device['product_id'], device['id'])
            if 'groupsArray' in device_info and len(device_info['groupsArray']) > 0:
                switch_array_length = 0
                for bulb in device_info['bulbsArray']:
                    current_index = bulb['deviceID'] % 1000
                    if current_index > switch_array_length:
                        switch_array_length = current_index
                switches = [{}]*(switch_array_length+1)
                home_hub_index = switch_array_length
                for bulb in device_info['bulbsArray']:
                    if 'switchID' in bulb and bulb['switchID'] != 0:
                        current_index = bulb['deviceID'] % 1000
                        if current_index < home_hub_index:
                            home_hub_index = current_index
                        switches[current_index] = {'id':str(bulb['switchID']),'name':bulb['displayName']}
                for group in device_info['groupsArray']:
                    if len(group['deviceIDArray']) > 0:
                        room_name = group['displayName']
                        switch_array = {switches[i]['id']:{'name':switches[i]['name'],'state':False,'brightness':0} for i in group['deviceIDArray'] if switches[i] != {}}
                        switch_names_list = [switches[i]['name'] for i in group['deviceIDArray'] if switches[i] != {}]
                        switch_names = [' and '.join(names) for names in [switch_names_list[i * 4:(i + 1) * 4] for i in range((len(switch_names_list) + 4 - 1) //4)]]
                        switch_rooms_list.extend([{'id':switches[i]['id'], 'room':room_name, 'home_index':len(home_hubs)} for i in group['deviceIDArray'] if switches[i] != {}])
                        rooms.append({'name':room_name, 'switches':switch_array, 'switch_names':switch_names})
                home_hubs.append({'hub_id':int(switches[home_hub_index]['id']), 'hub_switches':switches})
        self.room_data = {'rooms':{room['name']:{'state':False,'brightness':0,'switches':room['switches'],'switch_names':room['switch_names']} for room in rooms},'switchID_to_room':{dev['id']:dev['room'] for dev in switch_rooms_list},'home_hubs':home_hubs,'switchID_to_home_index':{dev['id']:dev['home_index'] for dev in switch_rooms_list}}
        return self.room_data

    async def _get_devices(self):
        """Get a list of devices for a particular user."""
        headers = {'Access-Token': self.user_credentials['access_token']}
        async with aiohttp.ClientSession() as session:
            async with session.get(API_DEVICES.format(user=self.user_credentials['user_id']), headers=headers) as resp:
                response  = await resp.json()
                return response

    async def _get_properties(self, product_id, device_id):
        """Get properties for a single device."""
        headers = {'Access-Token': self.user_credentials['access_token']}
        async with aiohttp.ClientSession() as session:
            async with session.get(API_DEVICE_INFO.format(product_id=product_id, device_id=device_id), headers=headers) as resp:
                response = await resp.json()
                return response

class GetGoogleCredentials:

    def __init__(self):
        self.google_flow = None

    async def get_google_auth_url(self, hass, client_config, flow_id, redirect_uri):
        def flow():
            try:
                self.google_flow = InstalledAppFlow.from_client_config(client_config = client_config, scopes = ["https://www.googleapis.com/auth/assistant-sdk-prototype"], redirect_uri = redirect_uri)
            except:
                return {'valid_client_secret': False}
            else:
                auth_url,_ = self.google_flow.authorization_url(prompt='consent', state = flow_id)
                return {'valid_client_secret': True, 'auth_url': auth_url}

        return await hass.async_add_executor_job(flow)

    async def get_google_credentials(self, hass, code):
        def fetch():
            try:
                self.google_flow.fetch_token(code = code)
            except:
                return {'success':False}
            else:
                return {'success':True}
                
        return await hass.async_add_executor_job(fetch)

class TwoFactorCodeRequired(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class InvalidClientSecret(HomeAssistantError):
    """Error to indicate there is invalid client secret."""

class InvalidGoogleAuth(HomeAssistantError):
    """Error to indicate there is invalid google authorization code."""

class CyncAddonUnavailable(HomeAssistantError):
    """Error to indicate that the cync addon did not respond."""