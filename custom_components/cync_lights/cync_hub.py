import logging
import threading
import asyncio
import struct
import aiohttp
import math
import ssl
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
    "MOTION":[37,49,54],
    "AMBIENT_LIGHT":[37,49,54],
    "WIFICONTROL":[36,37,38,39,40,48,49,51,52,53,54,55,56,57,58,59,61,62,63,64,65,66,67,68,80,81,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,156,158,159,160,161,162,163,164,165],
    "PLUG":[64,65,66,67,68],
    "FAN":[81],
    "MULTIELEMENT":{'67':2}
}

class CyncHub:

    def __init__(self, user_data, options, remove_options_update_listener):

        self.thread = None
        self.loop = None
        self.reader = None
        self.writer = None
        self.login_code = bytearray(user_data['cync_credentials'])
        self.logged_in = False
        self.home_devices = user_data['cync_config']['home_devices']
        self.home_controllers = user_data['cync_config']['home_controllers']
        self.switchID_to_homeID = user_data['cync_config']['switchID_to_homeID']
        self.connected_devices = {home_id:[] for home_id in self.home_controllers.keys()}
        self.shutting_down = False
        self.remove_options_update_listener = remove_options_update_listener
        self.cync_rooms = {room_id:CyncRoom(room_id,room_info,self) for room_id,room_info in user_data['cync_config']['rooms'].items()}
        self.cync_switches = {device_id:CyncSwitch(device_id,switch_info,self.cync_rooms.get(switch_info['room'], None),self) for device_id,switch_info in user_data['cync_config']['devices'].items() if switch_info.get("ONOFF",False)}
        self.cync_motion_sensors = {device_id:CyncMotionSensor(device_id,device_info,self.cync_rooms.get(device_info['room'], None)) for device_id,device_info in user_data['cync_config']['devices'].items() if device_info.get("MOTION",False)}
        self.cync_ambient_light_sensors = {device_id:CyncAmbientLightSensor(device_id,device_info,self.cync_rooms.get(device_info['room'], None)) for device_id,device_info in user_data['cync_config']['devices'].items() if device_info.get("AMBIENT_LIGHT",False)}
        self.switchID_to_deviceIDs = {device_info.switch_id:[dev_id for dev_id, dev_info in self.cync_switches.items() if dev_info.switch_id == device_info.switch_id] for device_id, device_info in self.cync_switches.items() if int(device_info.switch_id) > 0}
        self.connected_devices_updated = False
        self.options = options
        self._seq_num = 0
        self.pending_commands = {}
        [room.initialize() for room in self.cync_rooms.values() if room.is_subgroup]
        [room.initialize() for room in self.cync_rooms.values() if not room.is_subgroup]
        
    def start_tcp_client(self):
        self.thread = threading.Thread(target=self._start_tcp_client,daemon=True)
        self.thread.start()

    def _start_tcp_client(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect())

    def disconnect(self):
        self.shutting_down = True
        for home_controllers in self.home_controllers.values(): #send packets to server to generate data to be read which will initiate shutdown
            for controller in home_controllers:
                seq = self.get_seq_num()
                state_request = bytes.fromhex('7300000018') + int(controller).to_bytes(4,'big') + seq.to_bytes(2,'big') + bytes.fromhex('007e00000000f85206000000ffff0000567e')
                self.loop.call_soon_threadsafe(self.send_request,state_request)

    async def _connect(self):
        while not self.shutting_down:
            try:
                context = ssl.create_default_context()
                try:
                    self.reader, self.writer = await asyncio.open_connection('cm.gelighting.com', 23779, ssl = context)
                except Exception as e:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    try:
                        self.reader, self.writer = await asyncio.open_connection('cm.gelighting.com', 23779, ssl = context)
                    except Exception as e:
                        self.reader, self.writer = await asyncio.open_connection('cm.gelighting.com', 23778)
            except Exception as e:
                _LOGGER.error(str(type(e).__name__) + ": " + str(e))
                await asyncio.sleep(5)
            else:
                read_tcp_messages = asyncio.create_task(self._read_tcp_messages(), name = "Read TCP Messages")
                maintain_connection = asyncio.create_task(self._maintain_connection(), name = "Maintain Connection")
                update_state = asyncio.create_task(self._update_state(), name = "Update State")
                update_connected_devices = asyncio.create_task(self._update_connected_devices(), name = "Update Connected Devices")
                read_write_tasks = [read_tcp_messages, maintain_connection, update_state, update_connected_devices]
                try:
                    done, pending = await asyncio.wait(read_write_tasks,return_when=asyncio.FIRST_EXCEPTION)
                    for task in done:
                        name = task.get_name()
                        exception = task.exception()
                        try:
                            result = task.result()
                        except Exception as e:
                            _LOGGER.error(str(type(e).__name__) + ": " + str(e))
                    for task in pending:
                        task.cancel()                    
                    if not self.shutting_down:
                        _LOGGER.error("Connection to Cync server reset, restarting in 15 seconds")
                        await asyncio.sleep(15)
                    else:
                        _LOGGER.debug("Cync client shutting down")
                except Exception as e:
                    _LOGGER.error(str(type(e).__name__) + ": " + str(e))

    async def _read_tcp_messages(self):
        self.writer.write(self.login_code)
        await self.writer.drain()
        await self.reader.read(1000)
        self.logged_in = True
        while not self.shutting_down:
            data = await self.reader.read(1000)
            if len(data) == 0:
                self.logged_in = False
                raise LostConnection
            while len(data) >= 12:
                packet_type = int(data[0])
                packet_length = struct.unpack(">I", data[1:5])[0]
                packet = data[5:packet_length+5]
                try:
                    if packet_length == len(packet):
                        if packet_type == 115:
                            switch_id = str(struct.unpack(">I", packet[0:4])[0])
                            home_id = self.switchID_to_homeID[switch_id]

                            #send response packet
                            response_id = struct.unpack(">H", packet[4:6])[0]
                            response_packet = bytes.fromhex('7300000007') + int(switch_id).to_bytes(4,'big') + response_id.to_bytes(2,'big') + bytes.fromhex('00')
                            self.loop.call_soon_threadsafe(self.send_request, response_packet)

                            if packet_length >= 33 and int(packet[13]) == 219:
                                #parse state and brightness change packet
                                deviceID = self.home_devices[home_id][int(packet[21])]
                                state = int(packet[27]) > 0
                                brightness = int(packet[28]) if state else 0
                                if deviceID in self.cync_switches:
                                    self.cync_switches[deviceID].update_switch(state,brightness,self.cync_switches[deviceID].color_temp,self.cync_switches[deviceID].rgb)
                            elif packet_length >= 25 and int(packet[13]) == 84:
                                #parse motion and ambient light sensor packet
                                deviceID = self.home_devices[home_id][int(packet[16])]
                                motion = int(packet[22]) > 0
                                ambient_light = int(packet[24]) > 0
                                if deviceID in self.cync_motion_sensors:
                                    self.cync_motion_sensors[deviceID].update_motion_sensor(motion)
                                if deviceID in self.cync_ambient_light_sensors:
                                    self.cync_ambient_light_sensors[deviceID].update_ambient_light_sensor(ambient_light)
                            elif packet_length > 51 and int(packet[13]) == 82:
                                #parse initial state packet
                                switch_id = str(struct.unpack(">I", packet[0:4])[0])
                                home_id = self.switchID_to_homeID[switch_id]
                                self._add_connected_devices(switch_id, home_id)
                                packet = packet[22:]
                                while len(packet) > 24:
                                    deviceID = self.home_devices[home_id][int(packet[0])]
                                    if deviceID in self.cync_switches:
                                        if self.cync_switches[deviceID].elements > 1:
                                            for i in range(self.cync_switches[deviceID].elements):
                                                device_id = self.home_devices[home_id][(i+1)*256 + int(packet[0])]
                                                state = int((int(packet[12]) >> i) & int(packet[8])) > 0
                                                brightness = 100 if state else 0
                                                self.cync_switches[device_id].update_switch(state, brightness, self.cync_switches[device_id].color_temp, self.cync_switches[device_id].rgb)
                                        else:
                                            state = int(packet[8]) > 0
                                            brightness = int(packet[12]) if state else 0
                                            color_temp = int(packet[16])
                                            rgb = {'r':int(packet[20]),'g':int(packet[21]),'b':int(packet[22]),'active':int(packet[16])==254}
                                            self.cync_switches[deviceID].update_switch(state,brightness,color_temp,rgb)
                                    packet = packet[24:]
                        elif packet_type == 131:
                            switch_id = str(struct.unpack(">I", packet[0:4])[0])
                            home_id = self.switchID_to_homeID[switch_id]
                            if packet_length >= 33 and int(packet[13]) == 219:
                                #parse state and brightness change packet
                                deviceID = self.home_devices[home_id][int(packet[21])]
                                state = int(packet[27]) > 0
                                brightness = int(packet[28]) if state else 0
                                if deviceID in self.cync_switches:
                                    self.cync_switches[deviceID].update_switch(state,brightness,self.cync_switches[deviceID].color_temp,self.cync_switches[deviceID].rgb)
                            elif packet_length >= 25 and int(packet[13]) == 84:
                                #parse motion and ambient light sensor packet
                                deviceID = self.home_devices[home_id][int(packet[16])]
                                motion = int(packet[22]) > 0
                                ambient_light = int(packet[24]) > 0
                                if deviceID in self.cync_motion_sensors:
                                    self.cync_motion_sensors[deviceID].update_motion_sensor(motion)
                                if deviceID in self.cync_ambient_light_sensors:
                                    self.cync_ambient_light_sensors[deviceID].update_ambient_light_sensor(ambient_light)
                        elif packet_type == 67 and packet_length >= 26 and int(packet[4]) == 1 and int(packet[5]) == 1 and int(packet[6]) == 6:
                            #parse state packet
                            switch_id = str(struct.unpack(">I", packet[0:4])[0])
                            home_id = self.switchID_to_homeID[switch_id]
                            packet = packet[7:]
                            while len(packet) >= 19:
                                if int(packet[3]) < len(self.home_devices[home_id]):
                                    deviceID = self.home_devices[home_id][int(packet[3])]
                                    if deviceID in self.cync_switches:
                                        if self.cync_switches[deviceID].elements > 1:
                                            for i in range(self.cync_switches[deviceID].elements):
                                                device_id = self.home_devices[home_id][(i+1)*256 + int(packet[3])]
                                                state = int((int(packet[5]) >> i) & int(packet[4])) > 0
                                                brightness = 100 if state else 0
                                                self.cync_switches[device_id].update_switch(state, brightness, self.cync_switches[device_id].color_temp, self.cync_switches[device_id].rgb)
                                        else:
                                            state = int(packet[4]) > 0
                                            brightness = int(packet[5]) if state else 0
                                            color_temp = int(packet[6])
                                            rgb = {'r':int(packet[7]),'g':int(packet[8]),'b':int(packet[9]),'active':int(packet[6])==254}
                                            self.cync_switches[deviceID].update_switch(state,brightness,color_temp,rgb)
                                packet = packet[19:]
                        elif packet_type == 171:
                            switch_id = str(struct.unpack(">I", packet[0:4])[0])
                            home_id = self.switchID_to_homeID[switch_id]
                            self._add_connected_devices(switch_id, home_id)
                        elif packet_type == 123:
                            seq = str(struct.unpack(">H", packet[4:6])[0])
                            command_received = self.pending_commands.get(seq,None)
                            if command_received is not None:
                                command_received(seq)
                except Exception as e:
                    _LOGGER.error(str(type(e).__name__) + ": " + str(e))
                data = data[packet_length+5:]
        raise ShuttingDown


    async def _maintain_connection(self):
        while not self.shutting_down:
            await asyncio.sleep(180)
            self.writer.write(bytes.fromhex('d300000000'))
            await self.writer.drain()
        raise ShuttingDown

    def _add_connected_devices(self,switch_id, home_id):
        for dev in self.switchID_to_deviceIDs[switch_id]:
            #update list of WiFi connected devices
            if dev not in self.connected_devices[home_id]:
                self.connected_devices[home_id].append(dev)
                if self.connected_devices_updated:
                    for dev in self.cync_switches.values():
                        dev.update_controllers()
                    for room in self.cync_rooms.values():
                        room.update_controllers() 

    async def _update_connected_devices(self):
        while not self.shutting_down:
            self.connected_devices_updated = False
            for devices in self.connected_devices.values():
                devices.clear()
            while not self.logged_in:
                await asyncio.sleep(2)
            attempts = 0
            while True in [len(devices) < len(self.home_controllers[home_id]) * 0.5 for home_id,devices in self.connected_devices.items()] and attempts < 10:
                for home_id, home_controllers in self.home_controllers.items():
                    for controller in home_controllers:
                        seq = self.get_seq_num()
                        ping = bytes.fromhex('a300000007') + int(controller).to_bytes(4,'big') + seq.to_bytes(2,'big') + bytes.fromhex('00')
                        self.loop.call_soon_threadsafe(self.send_request, ping)
                        await asyncio.sleep(0.15)
                await asyncio.sleep(2)
                attempts += 1            
            for dev in self.cync_switches.values():
                dev.update_controllers()
            for room in self.cync_rooms.values():
                room.update_controllers()
            self.connected_devices_updated = True
            await asyncio.sleep(3600)
        raise ShuttingDown

    async def _update_state(self):
        while not self.connected_devices_updated:
            await asyncio.sleep(2)
        for connected_devices in self.connected_devices.values():
            if len(connected_devices) > 0:
                controller = self.cync_switches[connected_devices[0]].switch_id
                seq = self.get_seq_num()
                state_request = bytes.fromhex('7300000018') + int(controller).to_bytes(4,'big') + seq.to_bytes(2,'big') + bytes.fromhex('007e00000000f85206000000ffff0000567e')
                self.loop.call_soon_threadsafe(self.send_request,state_request)
        while False in [self.cync_switches[dev_id]._update_callback is not None for dev_id in self.options["switches"]] and False in [self.cync_rooms[dev_id]._update_callback is not None for dev_id in self.options["rooms"]]:
            await asyncio.sleep(2)
        for dev in self.cync_switches.values():
            dev.publish_update()
        for room in self.cync_rooms.values():
            dev.publish_update()
            
    def send_request(self,request):
        async def send():
            self.writer.write(request)
            await self.writer.drain()
        self.loop.create_task(send())
        
    def combo_control(self,state,brightness,color_tone,rgb,switch_id,mesh_id,seq):
        combo_request = bytes.fromhex('7300000022') + int(switch_id).to_bytes(4,'big') + int(seq).to_bytes(2,'big') + bytes.fromhex('007e00000000f8f010000000000000') + mesh_id + bytes.fromhex('f00000') + (1 if state else 0).to_bytes(1,'big')  + brightness.to_bytes(1,'big') + color_tone.to_bytes(1,'big') + rgb[0].to_bytes(1,'big') + rgb[1].to_bytes(1,'big') + rgb[2].to_bytes(1,'big') + ((496 + int(mesh_id[0]) + int(mesh_id[1]) + (1 if state else 0) + brightness + color_tone + sum(rgb))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,combo_request)

    def turn_on(self,switch_id,mesh_id,seq):
        power_request = bytes.fromhex('730000001f') + int(switch_id).to_bytes(4,'big') + int(seq).to_bytes(2,'big') + bytes.fromhex('007e00000000f8d00d000000000000') + mesh_id + bytes.fromhex('d00000010000') + ((430 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,power_request)

    def turn_off(self,switch_id,mesh_id,seq):
        power_request = bytes.fromhex('730000001f') + int(switch_id).to_bytes(4,'big') + int(seq).to_bytes(2,'big') + bytes.fromhex('007e00000000f8d00d000000000000') + mesh_id + bytes.fromhex('d00000000000') + ((429 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,power_request)

    def set_color_temp(self,color_temp,switch_id,mesh_id,seq):
        color_temp_request = bytes.fromhex('730000001e') + int(switch_id).to_bytes(4,'big') + int(seq).to_bytes(2,'big') + bytes.fromhex('007e00000000f8e20c000000000000') + mesh_id + bytes.fromhex('e2000005') + color_temp.to_bytes(1,'big') + ((469 + int(mesh_id[0]) + int(mesh_id[1]) + color_temp)%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,color_temp_request)

    def get_seq_num(self):
        if self._seq_num == 65535:
            self._seq_num = 1
        else:
            self._seq_num += 1
        return self._seq_num

class CyncRoom:

    def __init__(self, room_id, room_info, hub):

        self.hub = hub
        self.room_id = room_id
        self.home_id = room_id.split('-')[0]
        self.name = room_info.get('name','unknown')
        self.home_name = room_info.get('home_name','unknown')
        self.parent_room = room_info.get('parent_room', 'unknown')
        self.mesh_id = int(room_info.get('mesh_id',0)).to_bytes(2,'little')
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active': False}
        self.switches = room_info.get('switches',[])
        self.subgroups = room_info.get('subgroups',[])
        self.is_subgroup = room_info.get('isSubgroup', False)
        self.all_room_switches = self.switches
        self.controllers = []
        self.default_controller = room_info.get('room_controller',self.hub.home_controllers[self.home_id][0])
        self._update_callback = None
        self._update_parent_room = None
        self.support_brightness = False
        self.support_color_temp = False
        self.support_rgb = False
        self.switches_support_brightness = False
        self.switches_support_color_temp = False
        self.switches_support_rgb = False
        self.groups_support_brightness = False
        self.groups_support_color_temp = False
        self.groups_support_rgb = False
        self._command_timout = 0.5
        self._command_retry_time = 5

    def initialize(self):
        """Initialization of supported features and registration of update function for all switches and subgroups in the room"""
        self.switches_support_brightness = [device_id for device_id in self.switches if self.hub.cync_switches[device_id].support_brightness]
        self.switches_support_color_temp = [device_id for device_id in self.switches if self.hub.cync_switches[device_id].support_color_temp]
        self.switches_support_rgb = [device_id for device_id in self.switches if self.hub.cync_switches[device_id].support_rgb]
        self.groups_support_brightness = [room_id for room_id in self.subgroups if self.hub.cync_rooms[room_id].support_brightness]
        self.groups_support_color_temp = [room_id for room_id in self.subgroups if self.hub.cync_rooms[room_id].support_color_temp]
        self.groups_support_rgb = [room_id for room_id in self.subgroups if self.hub.cync_rooms[room_id].support_rgb] 
        self.support_brightness = (len(self.switches_support_brightness) + len(self.groups_support_brightness)) > 0
        self.support_color_temp = (len(self.switches_support_color_temp) + len(self.groups_support_color_temp)) > 0
        self.support_rgb = (len(self.switches_support_rgb) + len(self.groups_support_rgb)) > 0
        for switch_id in self.switches:
            self.hub.cync_switches[switch_id].register_room_updater(self.update_room)
        for subgroup in self.subgroups:
            self.hub.cync_rooms[subgroup].register_room_updater(self.update_room)
            self.all_room_switches = self.all_room_switches + self.hub.cync_rooms[subgroup].switches
        for subgroup in self.subgroups:
            self.hub.cync_rooms[subgroup].all_room_switches = self.all_room_switches

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def register_room_updater(self, parent_updater):
        self._update_parent_room = parent_updater

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    async def turn_on(self, attr_rgb, attr_br, attr_ct) -> None:
        """Turn on the light."""
        attempts = 0
        update_received = False
        while not update_received and attempts < int(self._command_retry_time/self._command_timout):
            seq = str(self.hub.get_seq_num())
            if len(self.controllers) > 0:
                controller = self.controllers[attempts%len(self.controllers)]
            else:
                controller = self.default_controller
            if attr_rgb is not None and attr_br is not None:
                if math.isclose(attr_br, max([self.rgb['r'],self.rgb['g'],self.rgb['b']])*self.brightness/100, abs_tol = 2):
                    self.hub.combo_control(True, self.brightness, 254, attr_rgb, controller, self.mesh_id, seq)
                else:
                    self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], controller, self.mesh_id, seq)
            elif attr_rgb is None and attr_ct is None and attr_br is not None:
                self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], controller, self.mesh_id, seq)
            elif attr_rgb is not None and attr_br is None:
                self.hub.combo_control(True, self.brightness, 254, attr_rgb, controller, self.mesh_id, seq)
            elif attr_ct is not None:
                ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
                self.hub.set_color_temp(ct, controller, self.mesh_id, seq)
            else:
                self.hub.turn_on(controller, self.mesh_id, seq)
            self.hub.pending_commands[seq] = self.command_received
            await asyncio.sleep(self._command_timout)
            if self.hub.pending_commands.get(seq, None) is not None:
                self.hub.pending_commands.pop(seq)
                attempts += 1
            else:
                update_received = True

    async def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        attempts = 0
        update_received = False
        while not update_received and attempts < int(self._command_retry_time/self._command_timout):
            seq = str(self.hub.get_seq_num())
            if len(self.controllers) > 0:
                controller = self.controllers[attempts%len(self.controllers)]
            else:
                controller = self.default_controller
            self.hub.turn_off(controller, self.mesh_id, seq)
            self.hub.pending_commands[seq] = self.command_received
            await asyncio.sleep(self._command_timout)
            if self.hub.pending_commands.get(seq, None) is not None:
                self.hub.pending_commands.pop(seq)
                attempts += 1
            else:
                update_received = True

    def command_received(self, seq):
        """Remove command from hub.pending_commands when a reply is received from Cync server"""
        if self.hub.pending_commands.get(seq) is not None:
            self.hub.pending_commands.pop(seq)

    def update_room(self):
        """Update the current state of the room"""
        _brightness = self.brightness
        _color_temp = self.color_temp
        _rgb = self.rgb
        _power_state = True in ([self.hub.cync_switches[device_id].power_state for device_id in self.switches] + [self.hub.cync_rooms[room_id].power_state for room_id in self.subgroups])
        if self.support_brightness:
            _brightness = round(sum([self.hub.cync_switches[device_id].brightness for device_id in self.switches] + [self.hub.cync_rooms[room_id].brightness for room_id in self.subgroups])/(len(self.switches) + len(self.subgroups)))
        else:
            _brightness = 100 if _power_state else 0
        if self.support_color_temp:
            _color_temp = round(sum([self.hub.cync_switches[device_id].color_temp for device_id in self.switches_support_color_temp] + [self.hub.cync_rooms[room_id].color_temp for room_id in self.groups_support_color_temp])/(len(self.switches_support_color_temp) + len(self.groups_support_color_temp)))
        if self.support_rgb:
            _rgb['r'] = round(sum([self.hub.cync_switches[device_id].rgb['r'] for device_id in self.switches_support_rgb] + [self.hub.cync_rooms[room_id].rgb['r'] for room_id in self.groups_support_rgb])/(len(self.switches_support_rgb) + len(self.groups_support_rgb)))
            _rgb['g'] = round(sum([self.hub.cync_switches[device_id].rgb['g'] for device_id in self.switches_support_rgb] + [self.hub.cync_rooms[room_id].rgb['g'] for room_id in self.groups_support_rgb])/(len(self.switches_support_rgb) + len(self.groups_support_rgb)))
            _rgb['b'] = round(sum([self.hub.cync_switches[device_id].rgb['b'] for device_id in self.switches_support_rgb] + [self.hub.cync_rooms[room_id].rgb['b'] for room_id in self.groups_support_rgb])/(len(self.switches_support_rgb) + len(self.groups_support_rgb)))
            _rgb['active'] = True in ([self.hub.cync_switches[device_id].rgb['active'] for device_id in self.switches_support_rgb] + [self.hub.cync_rooms[room_id].rgb['active'] for room_id in self.groups_support_rgb])
        
        if _power_state != self.power_state or _brightness != self.brightness or _color_temp != self.color_temp or _rgb != self.rgb:
            self.power_state = _power_state
            self.brightness = _brightness
            self.color_temp = _color_temp
            self.rgb = _rgb
            self.publish_update()
            if self._update_parent_room:
                self._update_parent_room()

    def update_controllers(self):
        """Update the list of responsive, Wi-Fi connected controller devices"""
        connected_devices = self.hub.connected_devices[self.home_id]
        controllers = []
        if len(connected_devices) > 0:
            controllers = [self.hub.cync_switches[dev_id].switch_id for dev_id in self.all_room_switches if dev_id in connected_devices]
            others_available = [self.hub.cync_switches[dev_id].switch_id for dev_id in connected_devices]
            for controller in controllers:
                if controller in others_available:
                    others_available.remove(controller)
            self.controllers = controllers + others_available
        else:
            self.controllers = [self.default_controller]

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

class CyncSwitch:

    def __init__(self, device_id, switch_info, room, hub):
        self.hub = hub
        self.device_id = device_id
        self.switch_id = switch_info.get('switch_id','0')
        self.home_id = [home_id for home_id, home_devices in self.hub.home_devices.items() if self.device_id in home_devices][0]
        self.name = switch_info.get('name','unknown')
        self.home_name = switch_info.get('home_name','unknown')
        self.mesh_id = switch_info.get('mesh_id',0).to_bytes(2,'little')
        self.room = room
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active':False}
        self.default_controller = switch_info.get('switch_controller',self.hub.home_controllers[self.home_id][0])
        self.controllers = []
        self._update_callback = None
        self._update_parent_room = None
        self.support_brightness = switch_info.get('BRIGHTNESS',False)
        self.support_color_temp = switch_info.get('COLORTEMP',False)
        self.support_rgb = switch_info.get('RGB',False)
        self.plug = switch_info.get('PLUG',False)
        self.fan = switch_info.get('FAN',False)
        self.elements = switch_info.get('MULTIELEMENT',1)
        self._command_timout = 0.5
        self._command_retry_time = 5

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def register_room_updater(self, parent_updater):
        self._update_parent_room = parent_updater

    @property
    def max_mireds(self) -> int:
        """Return minimum supported color temperature."""
        return 500

    @property
    def min_mireds(self) -> int:
        """Return maximum supported color temperature."""
        return 200

    async def turn_on(self, attr_rgb, attr_br, attr_ct) -> None:
        """Turn on the light."""
        attempts = 0
        update_received = False
        while not update_received and attempts < int(self._command_retry_time/self._command_timout):
            seq = str(self.hub.get_seq_num())
            if len(self.controllers) > 0:
                controller = self.controllers[attempts%len(self.controllers)]
            else:
                controller = self.default_controller
            if attr_rgb is not None and attr_br is not None:
                if math.isclose(attr_br, max([self.rgb['r'],self.rgb['g'],self.rgb['b']])*self.brightness/100, abs_tol = 2):
                    self.hub.combo_control(True, self.brightness, 254, attr_rgb, controller, self.mesh_id, seq)
                else:
                    self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], controller, self.mesh_id, seq)
            elif attr_rgb is None and attr_ct is None and attr_br is not None:
                self.hub.combo_control(True, round(attr_br*100/255), 255, [255,255,255], controller, self.mesh_id, seq)
            elif attr_rgb is not None and attr_br is None:
                self.hub.combo_control(True, self.brightness, 254, attr_rgb, controller, self.mesh_id, seq)
            elif attr_ct is not None:
                ct = round(100*(self.max_mireds - attr_ct)/(self.max_mireds - self.min_mireds))
                self.hub.set_color_temp(ct, controller, self.mesh_id, seq)
            else:
                self.hub.turn_on(controller, self.mesh_id, seq)
            self.hub.pending_commands[seq] = self.command_received
            await asyncio.sleep(self._command_timout)
            if self.hub.pending_commands.get(seq, None) is not None:
                self.hub.pending_commands.pop(seq)
                attempts += 1
            else:
                update_received = True

    async def turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        attempts = 0
        update_received = False
        while not update_received and attempts < int(self._command_retry_time/self._command_timout):
            seq = str(self.hub.get_seq_num())
            if len(self.controllers) > 0:
                controller = self.controllers[attempts%len(self.controllers)]
            else:
                controller = self.default_controller
            self.hub.turn_off(controller, self.mesh_id, seq)
            self.hub.pending_commands[seq] = self.command_received
            await asyncio.sleep(self._command_timout)
            if self.hub.pending_commands.get(seq, None) is not None:
                self.hub.pending_commands.pop(seq)
                attempts += 1
            else:
                update_received = True

    def command_received(self, seq):
        """Remove command from hub.pending_commands when a reply is received from Cync server"""
        if self.hub.pending_commands.get(seq) is not None:
            self.hub.pending_commands.pop(seq)

    def update_switch(self,state,brightness,color_temp,rgb):
        """Update the state of the switch as updates are received from the Cync server"""
        self.update_received = True
        if self.power_state != state or self.brightness != brightness or self.color_temp != color_temp or self.rgb != rgb:
            self.power_state = state
            self.brightness = brightness if self.support_brightness and state else 100 if state else 0
            self.color_temp = color_temp 
            self.rgb = rgb
            self.publish_update()
            if self._update_parent_room:
                self._update_parent_room()

    def update_controllers(self):
        """Update the list of responsive, Wi-Fi connected controller devices"""
        connected_devices = self.hub.connected_devices[self.home_id]
        controllers = []
        if len(connected_devices) > 0:
            if int(self.switch_id) > 0:
                if self.device_id in connected_devices: 
                    #if this device is connected, make this the first available controller
                    controllers.append(self.switch_id)
            if self.room:
                controllers = controllers + [self.hub.cync_switches[device_id].switch_id for device_id in self.room.all_room_switches if device_id in connected_devices and device_id != self.device_id]
            others_available = [self.hub.cync_switches[device_id].switch_id for device_id in connected_devices]
            for controller in controllers:
                if controller in others_available:
                    others_available.remove(controller)
            self.controllers = controllers + others_available
        else:
            self.controllers = [self.default_controller]

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
        switchID_to_homeID = {}
        devices = {}
        rooms = {}
        homes = await self._get_homes()
        for home in homes:
            home_info = await self._get_home_properties(home['product_id'], home['id'])
            if home_info.get('groupsArray',False) and home_info.get('bulbsArray',False) and len(home_info['groupsArray']) > 0 and len(home_info['bulbsArray']) > 0:
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
                        'switch_id':str(device.get('switchID',0)), 
                        'ONOFF': device_type in Capabilities['ONOFF'], 
                        'BRIGHTNESS': device_type in Capabilities["BRIGHTNESS"], 
                        "COLORTEMP":device_type in Capabilities["COLORTEMP"], 
                        "RGB": device_type in Capabilities["RGB"], 
                        "MOTION": device_type in Capabilities["MOTION"], 
                        "AMBIENT_LIGHT": device_type in Capabilities["AMBIENT_LIGHT"], 
                        "WIFICONTROL": device_type in Capabilities["WIFICONTROL"],
                        "PLUG" : device_type in Capabilities["PLUG"],
                        "FAN" : device_type in Capabilities["FAN"],
                        'home_name':home['name'], 
                        'room':'', 
                        'room_name':''
                    }
                    if str(device_type) in Capabilities['MULTIELEMENT'] and current_index < 256:
                        devices[device_id]['MULTIELEMENT'] = Capabilities['MULTIELEMENT'][str(device_type)]
                    if devices[device_id].get('WIFICONTROL',False) and 'switchID' in device and device['switchID'] > 0:
                        switchID_to_homeID[str(device['switchID'])] = home_id
                        devices[device_id]['switch_controller'] = device['switchID']
                        home_controllers[home_id].append(device['switchID'])
                if len(home_controllers[home_id]) == 0:
                    for device in home_info['bulbsArray']:
                        device_id = str(device['deviceID'])
                        devices.pop(device_id,'')
                    home_devices.pop(home_id,'')
                    home_controllers.pop(home_id,'')
                else:
                    for room in home_info['groupsArray']:
                        if (len(room.get('deviceIDArray',[])) + len(room.get('subgroupIDArray',[]))) > 0:
                            room_id = home_id + '-' + str(room['groupID'])
                            room_controller = home_controllers[home_id][0]
                            available_room_controllers = [(id%1000) + (int(id/1000)*256) for id in room.get('deviceIDArray',[]) if 'switch_controller' in devices[home_devices[home_id][(id%1000)+(int(id/1000)*256)]]]
                            if len(available_room_controllers) > 0:
                                room_controller = devices[home_devices[home_id][available_room_controllers[0]]]['switch_controller']
                            for id in room.get('deviceIDArray',[]):
                                id = (id % 1000) + (int(id / 1000)*256)
                                devices[home_devices[home_id][id]]['room'] = room_id
                                devices[home_devices[home_id][id]]['room_name'] = room['displayName']
                                if 'switch_controller' not in devices[home_devices[home_id][id]] and devices[home_devices[home_id][id]].get('ONOFF',False):
                                    devices[home_devices[home_id][id]]['switch_controller'] = room_controller
                            rooms[room_id] = {'name':room['displayName'],
                                'mesh_id' : room['groupID'], 
                                'room_controller' : room_controller,
                                'home_name' : home['name'], 
                                'switches' : [home_devices[home_id][(i%1000)+(int(i/1000)*256)] for i in room.get('deviceIDArray',[]) if devices[home_devices[home_id][(i%1000)+(int(i/1000)*256)]].get('ONOFF',False)],
                                'isSubgroup' : room.get('isSubgroup',False),
                                'subgroups' : [home_id + '-' + str(subgroup) for subgroup in room.get('subgroupIDArray',[])]
                            }
                    for room,room_info in rooms.items():
                        if not room_info.get("isSubgroup",False) and len(subgroups := room_info.get("subgroups",[]).copy()) > 0:
                            for subgroup in subgroups:
                                if rooms.get(subgroup,None):
                                    rooms[subgroup]["parent_room"] = room_info["name"]
                                else:
                                    room_info['subgroups'].pop(room_info['subgroups'].index(subgroup))
                                    
        if len(rooms) == 0 or len(devices) == 0 or len(home_controllers) == 0 or len(home_devices) == 0 or len(switchID_to_homeID) == 0:
            raise InvalidCyncConfiguration
        else:
            return {'rooms':rooms, 'devices':devices, 'home_devices':home_devices, 'home_controllers':home_controllers, 'switchID_to_homeID':switchID_to_homeID}

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

class InvalidCyncConfiguration(Exception):
    """Cync configuration is not supported"""
