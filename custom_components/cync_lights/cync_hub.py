import asyncio
import struct
from homeassistant.core import HomeAssistant
from .assistant_text_query import GoogleAssistantTextRequest

SYNC_MSG = bytes.fromhex('43000000')
PIPE_SYNC_MSG = bytes.fromhex('83000000')
STATE_CHANGE_MSG = bytes.fromhex('01010605')

class CyncHub:

    def __init__(self, hass: HomeAssistant, user_data):
        self.cync_credentials = user_data['cync_credentials']
        self.google_credentials = user_data['google_credentials']
        self.cync_rooms = {room['name']:CyncRoom(room,self) for room in user_data['cync_room_data']['rooms']}
        self.id_to_room = user_data['cync_room_data']['switchID_to_room']
        self.login_code = bytearray.fromhex('13000000') + (10 + len(self.cync_credentials['authorize'])).to_bytes(1,'big') + bytearray.fromhex('03') + self.cync_credentials['user_id'].to_bytes(4,'big') + len(self.cync_credentials['authorize']).to_bytes(2,'big') + bytearray(self.cync_credentials['authorize'],'ascii') + bytearray.fromhex('0000b4')
        self.google = GoogleAssistantTextRequest(self.google_credentials)
        self.hass = hass

    async def start_tcp_client(self):
        reader, writer = await asyncio.open_connection('cm.gelighting.com', 23778)
        writer.write(self.login_code)
        await writer.drain()

        self.hass.async_create_task(self._maintain_connection(writer))
        self.hass.async_create_task(self._read_tcp_messages(reader))

    async def _read_tcp_messages(self,reader):
        while True:
            data = await reader.read(1000)
            msg_indices = [x for x in range(len(data)) if (data[x:x+4] == SYNC_MSG or data[x:x+4] == PIPE_SYNC_MSG) and data[x+9:x+13] == STATE_CHANGE_MSG]
            for msg_index in msg_indices:
                switchID = struct.unpack(">I", data[msg_index+5:msg_index+9])[0]
                state = int(data[msg_index+16]) > 0
                brightness = int(data[msg_index+17])
                room_name = self.id_to_room[switchID]
                room = self.cync_rooms[room_name]
                room.update_room(switchID,state,brightness)

    async def _maintain_connection(self,writer):
        while True:
            await asyncio.sleep(180)
            writer.write(self.login_code)
            await writer.drain()

    async def google_assistant_request(self,query):
        await self.hass.async_add_executor_job(self.google.assist(query))
        self.google_credentials = self.google.credentials
        
class CyncRoom:

    def __init__(self, room, hub):
        self._name = room['name']
        self._state = room['state']
        self._brightness = room['brightness']
        self._switches = room['switches']
        self._callback = None
        self.hub = hub

    def register_callback(self, callback) -> None:
        """Register callback, called when Room changes state."""
        self._callback = callback

    def remove_callback(self) -> None:
        """Remove previously registered callback."""
        self._callback = None

    async def update_room(self,switchID,state,brightness):
        self._switches[switchID]['state'] = state
        self._switches[switchID]['brightness'] = brightness
        if state != self._state and brightness != self._brightness:
            all_switches_changed = True
            for sw in self._switches:
                if sw['state'] != state and sw['brightness'] != brightness:
                    all_switches_changed = False
            if all_switches_changed:
                self._state = state
                self._brightness = brightness
                self.publish_update()

    async def turn_on(self,brightness):
        query = 'Set brightness to %d' % (brightness) + '%' + ' for'
        for sw in self._switches:
            query = query + ' and ' + sw['name']
        query = query.replace(' and','',1)
        self.hub.google_assistant_request(query)

    async def turn_off(self):
        query = 'Turn off'
        for sw in self._switches:
            query = query + ' and ' + sw['name']
        query = query.replace(' and','',1)
        self.hub.google_assistant_request(query)

    async def publish_update(self):
        self._callback()

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def brightness(self):
        return self._brightness