import logging
import threading
import asyncio
import struct
import aiohttp
import math
from typing import Any

_LOGGER = logging.getLogger(__name__)

API_AUTH = "https://api.gelighting.com/v2/user_auth"
API_REQUEST_CODE = "https://api.gelighting.com/v2/two_factor/email/verifycode"
API_2FACTOR_AUTH = "https://api.gelighting.com/v2/user_auth/two_factor"
API_DEVICES = "https://api.gelighting.com/v2/user/{user}/subscribe/devices"
API_DEVICE_INFO = "https://api.gelighting.com/v2/product/{product_id}/device/{device_id}/property"

Capabilities = {
    "ONOFF":[1,5,6,7,8,9,10,11,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,48,49,51,52,53,54,55,56,57,58,59,61,62,63,64,65,66,67,68,80,81,82,83,85,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,158,159,160,161,162,163,164,165],
    "BRIGHTNESS":[1,5,6,7,8,9,10,11,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,48,49,55,56,80,81,82,83,85,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,158,159,160,161,162,163,164,165],
    "COLORTEMP":[5,6,7,8,10,11,14,15,19,20,21,22,23,25,26,28,29,30,31,32,33,34,35,80,82,83,85,129,130,131,132,133,135,136,137,138,139,140,141,142,143,144,145,146,147,153,154,156,158,159,160,161,162,163,164,165],
    "RGB":[6,7,8,21,22,23,30,31,32,33,34,35,131,132,133,137,138,139,140,141,142,143,146,147,153,154,156,158,159,160,161,162,163,164,165],
    "MOTION":[37,49,54,56],
    "AMBIENT_LIGHT":[37,49,54,56],
    "WIFICONTROL":[36,37,38,39,40,48,49,51,52,53,54,55,56,57,58,59,61,62,63,64,65,66,67,68,80,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,158,159,160,161,162,163,164,165],
    "PLUG":[64,65,66,67,68],
    "MULTIELEMENT":{'67':2}
}

class CyncHub:

    def __init__(self, user_data, remove_options_update_listener):

        self.thread = None
        self.loop = None
        self.reader = None
        self.writer = None
        self.home_devices = user_data['cync_config']['home_devices']
        self.home_controllers = user_data['cync_config']['home_controllers']
        self.deviceID_to_home = user_data['cync_config']['deviceID_to_home']
        self.login_code = bytearray(user_data['cync_credentials'])
        self.logged_in = False
        self.cync_rooms = {room_id:CyncRoom(room_id,room_info,self) for room_id,room_info in user_data['cync_config']['rooms'].items()}
        self.cync_switches = {switch_id:CyncSwitch(switch_id,switch_info,self.cync_rooms.get(switch_info['room'], None),self) for switch_id,switch_info in user_data['cync_config']['devices'].items() if switch_info.get("ONOFF",False)}
        self.cync_motion_sensors = {device_id:CyncMotionSensor(device_id,device_info,self.cync_rooms.get(device_info['room'], None)) for device_id,device_info in user_data['cync_config']['devices'].items() if device_info.get("MOTION",False)}
        self.cync_ambient_light_sensors = {device_id:CyncAmbientLightSensor(device_id,device_info,self.cync_rooms.get(device_info['room'], None)) for device_id,device_info in user_data['cync_config']['devices'].items() if device_info.get("AMBIENT_LIGHT",False)}
        self.shutting_down = False
        self.remove_options_update_listener = remove_options_update_listener

    def start_tcp_client(self):
        self.thread = threading.Thread(target=self._start_tcp_client,daemon=True)
        self.thread.start()

    def _start_tcp_client(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect())

    def disconnect(self):
        self.shutting_down = True

    async def _connect(self):
        while not self.shutting_down:
            try:
                self.reader, self.writer = await asyncio.open_connection('cm.gelighting.com', 23778)
            except Exception as e:
                _LOGGER.error(str(type(e).__name__) + ": " + str(e))
            else:
                read_write_tasks = [self._read_tcp_messages(),self._maintain_connection()]
                await asyncio.wait(read_write_tasks,return_when=asyncio.FIRST_EXCEPTION)
                if not self.shutting_down:
                    _LOGGER.error("Connection to Cync server reset, restarting in 15 seconds")
                    await asyncio.sleep(15)
                else:
                    _LOGGER.error("Cync client shutting down")

    async def _read_tcp_messages(self):
        self.writer.write(self.login_code)
        await self.writer.drain()
        await self.reader.read(1000)
        self.logged_in = True
        while not self.shutting_down:
            data = await self.reader.read(1000)
            if len(data) == 0:
                raise LostConnection
            while len(data) >= 30:
                packet_type = int(data[0])
                packet_length = struct.unpack(">I", data[1:5])[0]
                packet = data[5:packet_length+5]
                data = data[packet_length+5:]
                try:
                    if (packet_type == 115 or packet_type == 131) and packet_length >= 33 and int(packet[13]) == 219:
                        #parse state and brightness change packet
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        deviceID = self.home_devices[home_id][struct.unpack("<H", packet[21:23])[0]]
                        state = int(packet[27]) > 0
                        brightness = int(packet[28])
                        if deviceID in self.cync_switches:
                            self.cync_switches[deviceID].update_switch(state,brightness,self.cync_switches[deviceID].color_temp,self.cync_switches[deviceID].rgb)
                    elif packet_type == 67 and packet_length >= 26 and int(packet[4]) == 1 and int(packet[5]) == 1 and int(packet[6]) == 6:
                        #parse state packet
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        packet = packet[7:]
                        while len(packet) >= 19:
                            deviceID = self.home_devices[home_id][int(packet[3])]
                            if deviceID in self.cync_switches:
                                if self.cync_switches[deviceID].elements > 1:
                                    for i in range(self.cync_switches[deviceID].elements):
                                        switch_id = self.home_devices[home_id][(i+1)*256 + int(packet[3])]
                                        state = int((int(packet[5]) >> i) & int(packet[4])) > 0
                                        brightness = 100 if state else 0
                                        self.cync_switches[switch_id].update_switch(state, brightness, self.cync_switches[switch_id].color_temp, self.cync_switches[switch_id].rgb)
                                else:
                                    state = int(packet[4]) > 0
                                    brightness = int(packet[5])
                                    color_temp = int(packet[6])
                                    rgb = {'r':int(packet[7]),'g':int(packet[8]),'b':int(packet[9]),'active':int(packet[6])==254}
                                    self.cync_switches[deviceID].update_switch(state,brightness,color_temp,rgb)
                            packet = packet[19:]
                    elif (packet_type == 115 or packet_type == 131) and packet_length >= 25 and int(packet[13]) == 84:
                        #parse motion and ambient light sensor packet
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        deviceID = self.home_devices[home_id][int(packet[16])]
                        motion = int(packet[22]) > 0
                        ambient_light = int(packet[24]) > 0
                        if deviceID in self.cync_motion_sensors:
                            self.cync_motion_sensors[deviceID].update_motion_sensor(motion)
                        if deviceID in self.cync_ambient_light_sensors:
                            self.cync_ambient_light_sensors[deviceID].update_ambient_light_sensor(ambient_light)
                    elif packet_type == 115 and packet_length > 51 and int(packet[13]) == 82:
                        #parse initial state packet
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        packet = packet[22:]
                        while len(packet) > 24:
                            deviceID = self.home_devices[home_id][int(packet[0])]
                            if deviceID in self.cync_switches:
                                if self.cync_switches[deviceID].elements > 1:
                                    for i in range(self.cync_switches[deviceID].elements):
                                        switch_id = self.home_devices[home_id][(i+1)*256 + int(packet[0])]
                                        state = int((int(packet[12]) >> i) & int(packet[8])) > 0
                                        brightness = 100 if state else 0
                                        self.cync_switches[switch_id].update_switch(state, brightness, self.cync_switches[switch_id].color_temp, self.cync_switches[switch_id].rgb)
                                else:
                                    state = int(packet[8]) > 0
                                    brightness = int(packet[12])
                                    color_temp = int(packet[16])
                                    rgb = {'r':int(packet[20]),'g':int(packet[21]),'b':int(packet[22]),'active':int(packet[16])==254}
                                    self.cync_switches[deviceID].update_switch(state,brightness,color_temp,rgb)
                            packet = packet[24:]
                except Exception as e:
                    _LOGGER.error(e)
        raise ShuttingDown

    async def _maintain_connection(self):
        while not self.shutting_down:
            await asyncio.sleep(180)
            self.writer.write(self.login_code)
            await self.writer.drain()
        raise ShuttingDown

    def send_request(self,request):

        async def send():
            self.writer.write(request)
            await self.writer.drain()

        self.loop.create_task(send())
        
    def combo_control(self,state,brightness,color_tone,rgb,switch_id,mesh_id):
        combo_request = bytes.fromhex('7300000022') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8f010000000000000') + mesh_id + bytes.fromhex('f00000') + (1 if state else 0).to_bytes(1,'big')  + brightness.to_bytes(1,'big') + color_tone.to_bytes(1,'big') + rgb[0].to_bytes(1,'big') + rgb[1].to_bytes(1,'big') + rgb[2].to_bytes(1,'big') + ((496 + int(mesh_id[0]) + int(mesh_id[1]) + (1 if state else 0) + brightness + color_tone + sum(rgb))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,combo_request)

    def turn_on(self,switch_id,mesh_id):
        power_request = bytes.fromhex('730000001f') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8d00d000000000000') + mesh_id + bytes.fromhex('d00000010000') + ((430 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,power_request)

    def turn_off(self,switch_id,mesh_id):
        power_request = bytes.fromhex('730000001f') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8d00d000000000000') + mesh_id + bytes.fromhex('d00000000000') + ((429 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,power_request)

    async def update_state(self):
        if self.logged_in:
            pass
        else:
            while not self.logged_in:
                await asyncio.sleep(1)
        for controllers in self.home_controllers.values():
            state_request = bytes.fromhex('7300000018') + int(controllers[0]).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f85206000000ffff0000567e')
            self.loop.call_soon_threadsafe(self.send_request,state_request)

class CyncRoom:

    def __init__(self, room_id, room_info, hub):

        self.hub = hub
        self.room_id = room_id
        self.name = room_info['name']
        self.home_name = room_info['home_name']
        self.mesh_id = int(room_info['mesh_id']).to_bytes(2,'little')
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active': False}
        self.switches = room_info['switches']
        self.controller = room_info['room_controller']
        self._update_callback = None
        self.support_brightness = True in [sw_info.get('BRIGHTNESS',False) for sw_info in self.switches.values()]
        self.support_color_temp = True in [sw_info.get('COLORTEMP',False) for sw_info in self.switches.values()]
        self.support_rgb = True in [sw_info.get('RGB',False) for sw_info in self.switches.values()]

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    def turn_on(self, attr_rgb, attr_br, attr_ct):

        if attr_rgb is not None and attr_br is not None:
            if math.isclose(attr_br, max([self.rgb['r'],self.rgb['g'],self.rgb['b']])*self.brightness/100, abs_tol = 2):
                self.hub.combo_control(True, self.brightness, 254, attr_rgb, self.controller, self.mesh_id)
            else:
                self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], self.controller, self.mesh_id)
        elif attr_rgb is None and attr_ct is None and attr_br is not None:
            self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], self.controller, self.mesh_id)
        elif attr_rgb is not None and attr_br is None:
            self.hub.combo_control(True, self.brightness, 254, attr_rgb, self.controller, self.mesh_id)
        elif attr_ct is not None:
            ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
            self.hub.combo_control(True, 255, ct, [0,0,0], self.controller, self.mesh_id)
        else:
            self.hub.turn_on(self.controller,self.mesh_id)

    def turn_off(self):
        self.hub.turn_off(self.controller, self.mesh_id)

    def update_room(self, switchID, state, brightness, color_temp, rgb):
        self.switches[switchID]['state'] = state
        self.switches[switchID]['brightness'] = brightness
        self.switches[switchID]['color_temp'] = color_temp
        self.switches[switchID]['rgb'] = rgb

        _power_state = True in [sw_info['state'] for sw_info in self.switches.values()]
        _brightness = round(sum([sw_info['brightness'] for sw_info in self.switches.values() if sw_info.get('BRIGHTNESS',False)])/len([sw_info for sw_info in self.switches.values() if sw_info.get('BRIGHTNESS',False)]))
        if self.support_color_temp:
            color_temp_list = [sw_info['color_temp'] for sw_info in self.switches.values() if sw_info['COLORTEMP']]
            _color_temp = round(sum(color_temp_list)/len(color_temp_list))
        else: 
            _color_temp = self.color_temp
        if self.support_rgb:
            r_list = [sw_info['rgb']['r'] for sw_info in self.switches.values() if sw_info.get('RGB',False)]
            g_list = [sw_info['rgb']['g'] for sw_info in self.switches.values() if sw_info.get('RGB',False)]
            b_list = [sw_info['rgb']['b'] for sw_info in self.switches.values() if sw_info.get('RGB',False)]
            active = True in [sw_info['rgb']['active'] for sw_info in self.switches.values() if sw_info.get('RGB',False)]
            _rgb = {'r':round(sum(r_list)/len(r_list)), 'g':round(sum(g_list)/len(r_list)), 'b':round(sum(b_list)/len(r_list)), 'active':active}
        else:
            _rgb = self.rgb
        
        if _power_state != self.power_state or _brightness != self.brightness or _color_temp != self.color_temp or _rgb != self.rgb:
            self.power_state = _power_state
            self.brightness = _brightness
            self.color_temp = _color_temp
            self.rgb = _rgb
            self.publish_update()

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

class CyncSwitch:

    def __init__(self, switch_id, switch_info, room, hub):
        
        self.hub = hub
        self.switch_id = switch_id
        self.name = switch_info['name']
        self.home_name = switch_info['home_name']
        self.mesh_id = switch_info['mesh_id'].to_bytes(2,'little')
        self.room = room
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active':False}
        self.controller = switch_info['switch_controller']
        self._update_callback = None
        self.support_brightness = switch_info.get('BRIGHTNESS',False)
        self.support_color_temp = switch_info.get('COLORTEMP',False)
        self.support_rgb = switch_info.get('RGB',False)
        self.plug = switch_info.get('PLUG',False)
        self.elements = switch_info.get('MULTIELEMENT',1)

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    def turn_on(self, attr_rgb, attr_br, attr_ct) -> None:
        """Turn on the light."""
        if attr_rgb is not None and attr_br is not None:
            if math.isclose(attr_br, max([self.rgb['r'],self.rgb['g'],self.rgb['b']])*self.brightness/100, abs_tol = 2):
                self.hub.combo_control(True, self.brightness, 254, attr_rgb, self.controller, self.mesh_id)
            else:
                self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], self.controller, self.mesh_id)
        elif attr_rgb is None and attr_ct is None and attr_br is not None:
            self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], self.controller, self.mesh_id)
        elif attr_rgb is not None and attr_br is None:
            self.hub.combo_control(True, self.brightness, 254, attr_rgb, self.controller, self.mesh_id)
        elif attr_ct is not None:
            ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
            self.hub.combo_control(True, 255, ct, [0,0,0], self.controller, self.mesh_id)
        else:
            self.hub.turn_on(self.controller, self.mesh_id)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self.hub.turn_off(self.controller, self.mesh_id)

    def update_switch(self,state,brightness,color_temp,rgb):
        if self.power_state != state or self.brightness != brightness or self.color_temp != color_temp or self.rgb != rgb:
            self.power_state = state
            self.brightness = brightness if self.support_brightness and state else 100 if state else 0
            self.color_temp = color_temp 
            self.rgb = rgb
            self.publish_update()
            if self.room:
                self.room.update_room(self.switch_id,self.power_state,self.brightness,self.color_temp,self.rgb)

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

class CyncMotionSensor:

    def __init__(self, device_id, device_info, room):
        
        self.device_id = device_id
        self.name = device_info['name']
        self.home_name = device_info['home_name']
        self.room = room
        self.motion = False
        self._update_callback = None

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def update_motion_sensor(self,motion):
        self.motion = motion
        self.publish_update()

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

class CyncAmbientLightSensor:

    def __init__(self, device_id, device_info, room):
        
        self.device_id = device_id
        self.name = device_info['name']
        self.home_name = device_info['home_name']
        self.room = room
        self.ambient_light = False
        self._update_callback = None

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def update_ambient_light_sensor(self,ambient_light):
        self.ambient_light = ambient_light
        self.publish_update()

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

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
                bulbs_array_length = max([((device['deviceID'] % home['id']) % 1000) + (int((device['deviceID'] % home['id']) / 1000)*256) for device in home_info['bulbsArray']]) + 1
                home_devices[home_id] = [""]*(bulbs_array_length)
                home_controllers[home_id] = []
                for device in home_info['bulbsArray']:
                    device_type = device['deviceType']
                    device_id = str(device['deviceID'])
                    current_index = ((device['deviceID'] % home['id']) % 1000) + (int((device['deviceID'] % home['id']) / 1000)*256)
                    home_devices[home_id][current_index] = device_id
                    devices[device_id] = {'name':device['displayName'],
                        'mesh_id':current_index, 
                        'ONOFF': device_type in Capabilities['ONOFF'], 
                        'BRIGHTNESS': device_type in Capabilities["BRIGHTNESS"], 
                        "COLORTEMP":device_type in Capabilities["COLORTEMP"], 
                        "RGB": device_type in Capabilities["RGB"], 
                        "MOTION": device_type in Capabilities["MOTION"], 
                        "AMBIENT_LIGHT": device_type in Capabilities["AMBIENT_LIGHT"], 
                        "WIFICONTROL": device_type in Capabilities["WIFICONTROL"],
                        "PLUG" : device_type in Capabilities["PLUG"],
                        'home_name':home['name'], 
                        'room':'', 
                        'room_name':''
                    }
                    if str(device_type) in Capabilities['MULTIELEMENT'] and current_index < 256:
                        devices[device_id]['MULTIELEMENT'] = Capabilities['MULTIELEMENT'][str(device_type)]
                    if devices[device_id].get('WIFICONTROL',False) and 'switchID' in device and device['switchID'] > 0:
                        deviceID_to_home[str(device['switchID'])] = home_id
                        devices[device_id]['switch_controller'] = device['switchID']
                        home_controllers[home_id].append(device['switchID'])
                for room in home_info['groupsArray']:
                    if len(room['deviceIDArray']) > 0 and len(home_controllers[home_id]) > 0:
                        room_id = home_id + '-' + str(room['groupID'])
                        room_controller = home_controllers[home_id][0]
                        available_room_controllers = [(id%1000) + (int(id/1000)*256) for id in room['deviceIDArray'] if 'switch_controller' in devices[home_devices[home_id][(id%1000)+(int(id/1000)*256)]]]
                        if len(available_room_controllers) > 0:
                            room_controller = devices[home_devices[home_id][available_room_controllers[0]]]['switch_controller']
                        for id in room['deviceIDArray']:
                            id = (id % 1000) + (int(id / 1000)*256)
                            devices[home_devices[home_id][id]]['room'] = room_id
                            devices[home_devices[home_id][id]]['room_name'] = room['displayName']
                            if 'switch_controller' not in devices[home_devices[home_id][id]] and devices[home_devices[home_id][id]].get('ONOFF',False):
                                devices[home_devices[home_id][id]]['switch_controller'] = room_controller
                        rooms[room_id] = {'name':room['displayName'],
                            'mesh_id': room['groupID'], 
                            'room_controller':room_controller,
                            'home_name':home['name'], 
                            'switches':{
                                home_devices[home_id][(i%1000)+(int(i/1000)*256)]:{
                                    'state':False, 
                                    'brightness':0, 
                                    'color_temp':0, 
                                    'rgb':{'r':0, 'g':0, 'b':0, 'active': False}, 
                                    'ONOFF':devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('ONOFF',False), 
                                    'BRIGHTNESS':devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('BRIGHTNESS',False), 
                                    'COLORTEMP':devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('COLORTEMP',False), 
                                    'RGB':devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('RGB',False)
                                } 
                                for i in room['deviceIDArray'] if devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('ONOFF',False)
                            }
                        }
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

class LostConnection(Exception):
    """Lost connection to Cync Server"""

class ShuttingDown(Exception):
    """Cync client shutting down"""