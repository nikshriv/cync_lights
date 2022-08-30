import logging
import threading
import asyncio
import struct
import time
from homeassistant.exceptions import HomeAssistantError
from .const import Capabilities

_LOGGER = logging.getLogger(__name__)

class CyncHub:

    def __init__(self, user_data):

        self.thread = None
        self.loop = None
        self.reader = None
        self.writer = None
        self.home_devices = user_data['cync_config']['home_devices']
        self.home_controllers = user_data['cync_config']['home_controllers']
        self.deviceID_to_home = user_data['cync_config']['deviceID_to_home']
        self.login_code = bytearray(user_data['cync_credentials'])
        self.logged_in = False
        self.options = user_data['options']
        self.cync_rooms = {room_id:CyncRoom(room_id,room_info) for room_id,room_info in user_data['cync_config']['rooms'].items()}
        self.cync_switches = {switch_id:CyncSwitch(switch_id,switch_info,self.cync_rooms[switch_info['room']]) for switch_id,switch_info in user_data['cync_config']['devices'].items() if switch_info["ONOFF"]}
        self.cync_motion_sensors = {device_id:CyncMotionSensor(device_id,device_info) for device_id,device_info in user_data['cync_config']['devices'].items() if device_info["MOTION"]}
        self.shutting_down = False

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
            while len(data) >= 5:
                packet_type = int(data[0])
                packet_length = struct.unpack(">I", data[1:5])[0]
                packet = data[5:packet_length+5]
                if len(data) > packet_length+5:
                    data = data[packet_length+5:]
                else:
                    data = []
                try:
                    if packet_type == 67 and packet_length >= 26 and int(packet[4]) == 1 and int(packet[5]) == 1 and int(packet[6]) == 6:
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        packet = packet[7:]
                        while len(packet) >= 19:
                            deviceID = self.home_devices[home_id][int(packet[3])]
                            state = int(packet[4]) > 0
                            brightness = int(packet[5])
                            color_temp = int(packet[6])
                            rgb = {'r':int(packet[7]),'g':int(packet[8]),'b':int(packet[9]),'active':int(packet[6])==254}
                            packet = packet[19:]
                            if deviceID in self.cync_switches:
                                self.cync_switches[deviceID].update_switch(state,brightness,color_temp,rgb)
                    elif (packet_type == 115 or packet_type == 131) and packet_length >= 28 and int(packet[13]) == 84:
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        deviceID = self.home_devices[home_id][int(packet[16])]
                        motion = int(packet[22]) > 0
                        if deviceID in self.cync_motion_sensors:
                            self.cync_motion_sensors[deviceID].update_motion_sensor(motion)
                    elif packet_type == 115 and packet_length > 51 and int(packet[13]) == 82:
                        home_id = self.deviceID_to_home[str(struct.unpack(">I", packet[0:4])[0])]
                        packet = packet[22:]
                        while len(packet) > 24:
                            deviceID = self.home_devices[home_id][int(packet[0])]
                            state = int(packet[8]) > 0
                            brightness = int(packet[12])
                            color_temp = int(packet[16])
                            rgb = {'r':int(packet[20]),'g':int(packet[21]),'b':int(packet[22]),'active':int(packet[16])==254}
                            if deviceID in self.cync_switches:
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
        
    def set_brightness(self,brightness,switch_id,mesh_id):
        brightness_request = bytes.fromhex('730000001d') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8d20b000000000000') + mesh_id + bytes.fromhex('d20000') + int(brightness).to_bytes(1,'big') + ((431 + int(mesh_id[0]) + int(mesh_id[1]) + int(brightness))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,brightness_request)

    def combo_control(self,brightness,color_tone,rgb,switch_id,mesh_id):
        combo_request = bytes.fromhex('7300000022') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8f010000000000000') + mesh_id + bytes.fromhex('f0000001') + brightness.to_bytes(1,'big') + color_tone.to_bytes(1,'big') + rgb[0].to_bytes(1,'big') + rgb[1].to_bytes(1,'big') + rgb[2].to_bytes(1,'big') + ((497 + int(mesh_id[0]) + int(mesh_id[1]) + brightness + color_tone + sum(rgb))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,combo_request)

    def set_rgb_color(self,rgb,switch_id,mesh_id):
        rgb_color_request = bytes.fromhex('7300000020') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8e20e000000000000') + mesh_id + bytes.fromhex('e2000004') + rgb[0].to_bytes(1,'big') + rgb[1].to_bytes(1,'big') + rgb[2].to_bytes(1,'big') + ((470 + int(mesh_id[0]) + int(mesh_id[1]) + sum(rgb))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,rgb_color_request)

    def set_color_temp(self,color_temp,switch_id,mesh_id):
        color_temp_request = bytes.fromhex('730000001e') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8e20c000000000000') + mesh_id + bytes.fromhex('e2000005') + color_temp.to_bytes(1,'big') + ((469 + int(mesh_id[0]) + int(mesh_id[1]) + color_temp)%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,color_temp_request)
        
    def turn_on(self,switch_id,mesh_id):
        power_request = bytes.fromhex('730000001d') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8d00b000000000000') + mesh_id + bytes.fromhex('d0000001') + ((428 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
        self.loop.call_soon_threadsafe(self.send_request,power_request)

    def turn_off(self,switch_id,mesh_id):
        power_request = bytes.fromhex('730000001d') + int(switch_id).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f8d00b000000000000') + mesh_id + bytes.fromhex('d0000000') + ((427 + int(mesh_id[0]) + int(mesh_id[1]))%256).to_bytes(1,'big') + bytes.fromhex('7e')
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

    def __init__(self, room_id, room_info):

        self.room_id = room_id
        self.name = room_info['name']
        self.mesh_id = int(room_info['mesh_id']).to_bytes(2,'little')
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active': False}
        self.switches = room_info['switches']
        self.room_controller = room_info['room_controller']
        self._update_callback = None
        self.support_brightness = True in [sw_info['BRIGHTNESS'] for sw_info in self.switches.values()]
        self.support_color_temp = True in [sw_info['COLORTEMP'] for sw_info in self.switches.values()]
        self.support_rgb = True in [sw_info['RGB'] for sw_info in self.switches.values()]

    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def update_room(self, switchID, state, brightness, color_temp, rgb):
        self.switches[switchID]['state'] = state
        self.switches[switchID]['brightness'] = brightness
        self.switches[switchID]['color_temp'] = color_temp
        self.switches[switchID]['rgb'] = rgb

        _power_state = True in [sw_info['state'] for sw_info in self.switches.values()]
        _brightness = round(sum([sw_info['brightness'] for sw_info in self.switches.values()])/len(self.switches))
        if self.support_color_temp:
            color_temp_list = [sw_info['color_temp'] for sw_info in self.switches.values() if sw_info['COLORTEMP']]
            _color_temp = round(sum(color_temp_list)/len(color_temp_list))
        else: 
            _color_temp = self.color_temp
        if self.support_rgb:
            r_list = [sw_info['rgb']['r'] for sw_info in self.switches.values() if sw_info['RGB']]
            g_list = [sw_info['rgb']['g'] for sw_info in self.switches.values() if sw_info['RGB']]
            b_list = [sw_info['rgb']['b'] for sw_info in self.switches.values() if sw_info['RGB']]
            active = True in [sw_info['rgb']['active'] for sw_info in self.switches.values() if sw_info['RGB']]
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

    def __init__(self, switch_id, switch_info, room):
        
        self.switch_id = switch_id
        self.name = switch_info['name']
        self.mesh_id = switch_info['mesh_id'].to_bytes(2,'little')
        self.room = room
        self.power_state = False
        self.brightness = 0
        self.color_temp = 0
        self.rgb = {'r':0, 'g':0, 'b':0, 'active':False}
        self.switch_controller = switch_info['switch_controller']
        self._update_callback = None
        self.support_brightness = switch_info['BRIGHTNESS']
        self.support_color_temp = switch_info['COLORTEMP']
        self.support_rgb = switch_info['RGB']


    def register(self, update_callback) -> None:
        """Register callback, called when switch changes state."""
        self._update_callback = update_callback

    def reset(self) -> None:
        """Remove previously registered callback."""
        self._update_callback = None

    def update_switch(self,state,brightness,color_temp,rgb):
        if self.power_state != state or self.brightness != brightness or self.color_temp != color_temp or self.rgb != rgb:
            self.power_state = state
            self.brightness = brightness if self.support_brightness else 100 if state else 0
            self.color_temp = color_temp 
            self.rgb = rgb
            self.publish_update()
            self.room.update_room(self.switch_id,self.power_state,self.brightness,self.color_temp,self.rgb)

    def publish_update(self):
        if self._update_callback:
            self._update_callback()

class CyncMotionSensor:

    def __init__(self, device_id, device_info):
        
        self.device_id = device_id
        self.name = device_info['name']
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

class LostConnection(HomeAssistantError):
    """Lost connection to Cync Server"""

class ShuttingDown(HomeAssistantError):
    """Cync client shutting down"""