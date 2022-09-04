"""Config flow for Cync Room Lights integration."""
from __future__ import annotations
import logging
import voluptuous as vol
import aiohttp
from typing import Any
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN,Capabilities

API_AUTH = "https://api.gelighting.com/v2/user_auth"
API_REQUEST_CODE = "https://api.gelighting.com/v2/two_factor/email/verifycode"
API_2FACTOR_AUTH = "https://api.gelighting.com/v2/user_auth/two_factor"
API_DEVICES = "https://api.gelighting.com/v2/user/{user}/subscribe/devices"
API_DEVICE_INFO = "https://api.gelighting.com/v2/product/{product_id}/device/{device_id}/property"

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

async def cync_login(hub, user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input"""

    response = await hub.authenticate(user_input["username"], user_input["password"])
    if response['authorized']:
        return {'title':'cync_lights_'+ user_input['username'],'data':{'cync_credentials': hub.auth_code}}
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

class CyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync Room Lights."""

    def __init__(self):
        self.cync_hub = CyncUserData()
        self.data ={}

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
            return await self.async_step_finish_setup()

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
            info["data"]["cync_config"] = await self.cync_hub.get_cync_config()
            info["data"]["options"] = {}
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            self.data = info
            return await self.async_step_select_switches()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


    async def async_step_select_switches(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select rooms and individual switches for entity creation"""
        if user_input is not None:
            self.data['data']['options']['rooms'] = user_input["rooms"]
            self.data['data']['options']['switches'] = user_input["switches"]
            self.data['data']['options']['motion_sensors'] = user_input["motion_sensors"]
            return await self._async_finish_setup()

        switches_data_schema = vol.Schema(
            {
                vol.Optional(
                    "rooms",
                    description = {"suggested_value" : [room for room in self.data["data"]["cync_config"]["rooms"].keys()]},
                ): cv.multi_select({room : f'{room_info["name"]} ({room_info["home_name"]})' for room,room_info in self.data["data"]["cync_config"]["rooms"].items()}),
                vol.Optional(
                    "switches",
                    description = {"suggested_value" : []},
                ): cv.multi_select({switch_id : f'{sw_info["name"]} ({self.data["data"]["cync_config"]["rooms"][sw_info["room"]]["name"]}:{sw_info["home_name"]})' for switch_id,sw_info in self.data["data"]["cync_config"]["devices"].items() if sw_info['ONOFF']}),
                vol.Optional(
                    "motion_sensors",
                    description = {"suggested_value" : [device_id for device_id,device_info in self.data["data"]["cync_config"]["devices"].items() if device_info['MOTION']]},
                ): cv.multi_select({device_id : f'{device_info["name"]} ({self.data["data"]["cync_config"]["rooms"][device_info["room"]]["name"]}:{device_info["home_name"]})' for device_id,device_info in self.data["data"]["cync_config"]["devices"].items() if device_info['MOTION']}),
            }
        )
        
        return self.async_show_form(step_id="select_switches", data_schema=switches_data_schema)

    async def _async_finish_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish setup and create entry"""

        existing_entry = await self.async_set_unique_id(self.data['title'])
        if not existing_entry:              
            return self.async_create_entry(title=self.data["title"], data=self.data["data"])
        else:
            self.hass.config_entries.async_update_entry(existing_entry, data=self.data['data'])
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")


class CyncUserData:

    def __init__(self):
        self.username = ''
        self.password = ''
        self.auth_code = None
        self.user_credentials = {}

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
        home_devices = {}
        home_controllers = {}
        deviceID_to_home = {}
        devices = {}
        rooms = {}
        homes = await self._get_homes()
        for home in homes:
            home_info = await self._get_home_properties(home['product_id'], home['id'])
            if 'groupsArray' in home_info and len(home_info['groupsArray']) > 0:
                home_id = str(home['id'])
                home_devices[home_id] = [""]*(len(home_info['bulbsArray'])+1)
                home_controllers[home_id] = []
                for device in home_info['bulbsArray']:
                    device_type = device['deviceType']
                    device_id = device['mac']
                    current_index = device['deviceID'] % 1000
                    home_devices[home_id][current_index] = device_id
                    devices[device_id] = {'name':device['displayName'],'mesh_id':current_index, 'ONOFF': device_type in Capabilities['ONOFF'], 'BRIGHTNESS': device_type in Capabilities["BRIGHTNESS"], "COLORTEMP":device_type in Capabilities["COLORTEMP"], "RGB": device_type in Capabilities["RGB"], "MOTION": device_type in Capabilities["MOTION"], "WIFICONTROL": device_type in Capabilities["WIFICONTROL"],'home_name':home['name']}
                    if devices[device_id]["WIFICONTROL"] and 'switchID' in device and device['switchID'] > 0:
                        deviceID_to_home[str(device['switchID'])] = home_id
                        devices[device_id]['switch_controller'] = device['switchID']
                        home_controllers[home_id].append(device['switchID'])
                for room in home_info['groupsArray']:
                    if len(room['deviceIDArray']) > 0:
                        room_id = home_id + '-' + str(room['groupID'])
                        room_controller = home_controllers[home_id][0]
                        available_room_controllers = [id for id in room['deviceIDArray'] if 'switch_controller' in devices[home_devices[home_id][id]]]
                        if len(available_room_controllers) > 0:
                            room_controller = devices[home_devices[home_id][available_room_controllers[0]]]['switch_controller']
                        for id in room['deviceIDArray']:
                            devices[home_devices[home_id][id]]['room'] = room_id
                            if 'switch_controller' not in devices[home_devices[home_id][id]] and devices[home_devices[home_id][id]]['ONOFF']:
                                devices[home_devices[home_id][id]]['switch_controller'] = room_controller
                        rooms[room_id] = {'name':room['displayName'],'mesh_id': room['groupID'], 'room_controller':room_controller,'home_name':home['name'], 'switches':{home_devices[home_id][i]:{'state':False, 'brightness':0, 'color_temp':0, 'rgb':{'r':0, 'g':0, 'b':0, 'active': False}, 'ONOFF':devices[home_devices[home_id][i]]['ONOFF'], 'BRIGHTNESS':devices[home_devices[home_id][i]]['BRIGHTNESS'], 'COLORTEMP':devices[home_devices[home_id][i]]['COLORTEMP'], 'RGB':devices[home_devices[home_id][i]]['RGB']} for i in room['deviceIDArray'] if devices[home_devices[home_id][i]]['ONOFF']}}
        return {'rooms':rooms, 'devices':devices, 'home_devices':home_devices, 'home_controllers':home_controllers, 'deviceID_to_home':deviceID_to_home}

    async def _get_homes(self):
        """Get a list of devices for a particular user."""
        headers = {'Access-Token': self.user_credentials['access_token']}
        async with aiohttp.ClientSession() as session:
            async with session.get(API_DEVICES.format(user=self.user_credentials['user_id']), headers=headers) as resp:
                response  = await resp.json()
                return response

    async def _get_home_properties(self, product_id, device_id):
        """Get properties for a single device."""
        headers = {'Access-Token': self.user_credentials['access_token']}
        async with aiohttp.ClientSession() as session:
            async with session.get(API_DEVICE_INFO.format(product_id=product_id, device_id=device_id), headers=headers) as resp:
                response = await resp.json()
                return response

class TwoFactorCodeRequired(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""