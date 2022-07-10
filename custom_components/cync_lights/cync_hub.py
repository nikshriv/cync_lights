import logging
import threading
import asyncio
import struct
import time
import google.auth.transport.grpc
import google.auth.transport.requests
import google.oauth2.credentials
from homeassistant.exceptions import HomeAssistantError
from google.assistant.embedded.v1alpha2 import (embedded_assistant_pb2,embedded_assistant_pb2_grpc)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
ASSISTANT_API_ENDPOINT = 'embeddedassistant.googleapis.com'
GRPC_DEADLINE = 60 * 3 + 5

class CyncHub:

    def __init__(self, user_data):
        self.assistant = GoogleAssistant(user_data['google_credentials'])
        self.cync_rooms = {room:CyncRoom(room,room_info,self.assistant) for room,room_info in user_data['cync_room_data']['rooms'].items()}
        self.id_to_room = user_data['cync_room_data']['switchID_to_room']
        self.home_hubs = user_data['cync_room_data']['home_hubs']
        self.id_to_home_index = user_data['cync_room_data']['switchID_to_home_index']
        self.login_code = bytearray(user_data['cync_credentials'])
        self.reading_packets = False
        self.thread = None
        self.loop = None
        self.reader = None
        self.writer = None

    def start_tcp_client(self):
        self.thread = threading.Thread(target=self._start_tcp_client,daemon=True)
        self.thread.start()

    def _start_tcp_client(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect())

    async def _connect(self):
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection('cm.gelighting.com', 23778)
            except Exception as e:
                _LOGGER.error(str(type(e).__name__) + ": " + str(e))
            else:
                read_write_tasks = [self._read_tcp_messages(),self._maintain_connection(),self._get_current_state()]
                await asyncio.wait(read_write_tasks,return_when=asyncio.FIRST_EXCEPTION)
                await asyncio.sleep(15)
                _LOGGER.error("Connection to Cync server reset, restarting in 15 seconds")

    async def _read_tcp_messages(self):
        self.writer.write(self.login_code)
        await self.writer.drain()
        await self.reader.read(1000)
        while True:
            self.reading_packets = True
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
                if packet_type == 67 or packet_type == 131:
                    if packet_length >= 13:
                        if struct.unpack(">I",packet[4:8])[0] == 16844293:
                            switchID = str(struct.unpack(">I", packet[0:4])[0])
                            state = int(packet[11]) > 0
                            brightness = round(int(packet[12])*255/100)
                            room_name = self.id_to_room[switchID]
                            room = self.cync_rooms[room_name]
                            room.update_room(switchID,state,brightness)
                elif packet_type == 115:
                    if packet_length > 51:
                        if int(packet[13]) == 82:
                            home_hub_id = str(struct.unpack(">I", packet[0:4])[0])
                            home_hub = self.home_hubs[self.id_to_home_index[home_hub_id]]
                            packet = packet[22:]
                            while len(packet) > 24:
                                current_switch = home_hub['hub_switches'][int(packet[0])]
                                if current_switch.get('id') != None:
                                    state = int(packet[8]) > 0
                                    brightness = round(int(packet[12]*255/100))
                                    room_name = self.id_to_room[current_switch['id']]
                                    room = self.cync_rooms[room_name]
                                    room.update_room(str(current_switch['id']),state,brightness)
                                packet = packet[24:]

    async def _maintain_connection(self):
        while True:
            await asyncio.sleep(180)
            self.writer.write(self.login_code)
            await self.writer.drain()

    async def _get_current_state(self):
        try:
            all_rooms_registered = False
            while not self.reading_packets and not all_rooms_registered:
                await asyncio.sleep(1)
                all_rooms_registered = len([room for room in self.cync_rooms if self.cync_rooms[room]._callback is None]) == 0
            for home_hub in self.home_hubs:
                await asyncio.sleep(2)
                state_request = bytes.fromhex('7300000018') + (home_hub['hub_id']).to_bytes(4,'big') + bytes.fromhex('0000007e00000000f85206000000ffff0000567e')
                self.writer.write(state_request)
                await self.writer.drain()
        except Exception as e:
            _LOGGER.error(e)

class CyncRoom:

    def __init__(self, room, room_info, assistant):
        self.name = room
        self.power_state = room_info['state']
        self.brightness = room_info['brightness']
        self.switches = room_info['switches']
        self.switch_names = room_info['switch_names']
        self.assistant = assistant
        self._callback = None

    def register_callback(self, callback) -> None:
        """Register callback, called when Room changes state."""
        self._callback = callback

    def remove_callback(self) -> None:
        """Remove previously registered callback."""
        self._callback = None

    def update_room(self,switchID,state,brightness):
        self.switches[switchID]['state'] = state
        self.switches[switchID]['brightness'] = brightness
        if not state not in [self.switches[sw]['state'] for sw in self.switches]:
            self.brightness = round(sum([self.switches[sw]['brightness'] for sw in self.switches])/len(self.switches))
            self.power_state = state
            self.publish_update()

    def set_brightness(self,brightness):
        for group in self.switch_names:
            query = f'Set {group} to {round(100*brightness/255)}%'
            self.assistant.assist(query)    
    
    def turn_on(self):
        for group in self.switch_names:
            query = f'Turn on {group}'
            self.assistant.assist(query)

    def turn_off(self):
        for group in self.switch_names:
            query = f'Turn off {group}'
            self.assistant.assist(query)

    def publish_update(self):
        if self._callback:
            self._callback()

class GoogleAssistant():

    def __init__(self, credentials):
        self.credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(credentials)
        self.http_request = google.auth.transport.requests.Request()
        self.grpc_channel = None
        self.assistant = None

    def assist(self, text_query):

        def send_query():
            self.grpc_channel = google.auth.transport.grpc.secure_authorized_channel(self.credentials, self.http_request, ASSISTANT_API_ENDPOINT)
            self.assistant = embedded_assistant_pb2_grpc.EmbeddedAssistantStub(self.grpc_channel)

            def iter_assist_requests():
                config = embedded_assistant_pb2.AssistConfig(
                    audio_out_config=embedded_assistant_pb2.AudioOutConfig(
                        encoding='LINEAR16',
                        sample_rate_hertz=16000,
                        volume_percentage=0,
                    ),
                    dialog_state_in=embedded_assistant_pb2.DialogStateIn(
                        language_code = 'en-US',
                        conversation_state = None,
                        is_new_conversation = True,
                    ),
                    device_config=embedded_assistant_pb2.DeviceConfig(
                        device_id='5a1b2c3d4',
                        device_model_id='assistant',
                    ),
                    text_query=text_query
                )
                req = embedded_assistant_pb2.AssistRequest(config=config)
                yield req

            [resp for resp in self.assistant.Assist(iter_assist_requests(),GRPC_DEADLINE)]
            #self.credentials.refresh(self.http_request)
        
        assistant_thread = threading.Thread(target=send_query())
        assistant_thread.start()
        assistant_thread.join()
        
class LostConnection(HomeAssistantError):
    """Lost connection to Cync Server"""