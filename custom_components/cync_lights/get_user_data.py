import aiohttp
from google_auth_oauthlib.flow import InstalledAppFlow
from homeassistant.core import HomeAssistant

API_AUTH = "https://api.gelighting.com/v2/user_auth"
API_REQUEST_CODE = "https://api.gelighting.com/v2/two_factor/email/verifycode"
API_2FACTOR_AUTH = "https://api.gelighting.com/v2/user_auth/two_factor"
API_DEVICES = "https://api.gelighting.com/v2/user/{user}/subscribe/devices"
API_DEVICE_INFO = "https://api.gelighting.com/v2/product/{product_id}/device/{device_id}/property"

class GetCyncUserData:

    def __init__(self):
        self.username = ''
        self.password = ''
        self.auth_code = None
        self.user_credentials = None
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
        for device in devices:
            device_info = await self._get_properties(device['product_id'], device['id'])
            if 'groupsArray' in device_info and len(device_info['groupsArray']) > 0:
                switches = [0]*(len(device_info['bulbsArray'])+1)
                for bulb in device_info['bulbsArray']:
                    switches[bulb['deviceID'] % 1000] = {}
                    if bulb['switchID'] != 0:
                        switches[bulb['deviceID'] % 1000] = {'id':str(bulb['switchID']),'name':bulb['displayName']}
                for group in device_info['groupsArray']:
                    if len(group['deviceIDArray']) > 0:
                        room_name = group['displayName']
                        switch_array = {switches[i]['id']:{'name':switches[i]['name'],'state':False,'brightness':0} for i in group['deviceIDArray'] if switches[i] != {}}
                        switch_rooms_list.extend([{'id':switches[i]['id'], 'room':room_name} for i in group['deviceIDArray'] if switches[i] != {}])
                        rooms.append({'name':room_name, 'switches':switch_array})
        self.room_data = {'rooms':{room['name']:{'entity_id':'','state':False,'brightness':0,'switches':room['switches']} for room in rooms},'switchID_to_room':{dev['id']:dev['room'] for dev in switch_rooms_list}}
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

    async def get_google_auth_url(self, hass, client_config):
        def flow():
            try:
                self.google_flow = InstalledAppFlow.from_client_config(client_config = client_config, scopes = ["https://www.googleapis.com/auth/assistant-sdk-prototype"], redirect_uri = 'urn:ietf:wg:oauth:2.0:oob' )
            except:
                return {'valid_client_secret': False}
            else:
                auth_url,_ = self.google_flow.authorization_url(prompt='consent')
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