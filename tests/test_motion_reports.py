"""Replay public protocol examples through the native parser without network I/O.

Motion on/off:
https://github.com/baudneo/cync-lan/issues/38#issuecomment-6089494528
Ordinary light payload:
https://github.com/dash16/homebridge-cync-app/issues/37
Type 49 fa54 inner capture:
https://github.com/baudneo/cync-lan/issues/38#issuecomment-6182772529

Outer controller IDs in the public examples are replaced with synthetic values.
All configuration names, home/device IDs, and login bytes are synthetic. The
fa54 outer transport envelope is synthesized around the published inner capture.
No private captures or account data are used.

Run with: python -m unittest discover -s tests -v
The integration's aiohttp dependency is needed; Home Assistant is not imported.
"""

import asyncio
import copy
import importlib.util
import logging
from pathlib import Path
import unittest


HUB_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "cync_lights" / "cync_hub.py"
)

MOTION_ON = bytes.fromhex(
    "43 00 00 00 1a 01 02 03 04 01 01 06 02 00 02 ff "
    "01 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
)
MOTION_OFF = bytes.fromhex(
    "43 00 00 00 1a 01 02 03 04 01 01 06 02 00 02 ff "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
)
LIGHT = bytes.fromhex(
    "43 00 00 00 1a 05 06 07 08 01 01 06 05 00 10 11 "
    "01 1c 18 ff da 00 01 00 11 00 00 00 00 00 00"
)
MOTION_SWITCH = str(int.from_bytes(MOTION_ON[5:9], "big"))
LIGHT_SWITCH = str(int.from_bytes(LIGHT[5:9], "big"))
HOME = "100000"
SENSOR = "100000005"
OTHER_SENSOR = "100000006"
LAMP = "100000017"
TRAP = "100000255"


def frame(kind, payload):
    return bytes([kind]) + len(payload).to_bytes(4, "big") + payload


FA54 = frame(
    0x73,
    int(MOTION_SWITCH).to_bytes(4, "big")
    + bytes.fromhex(
        "00 01 00 7e 00 00 00 00 fa 54 0a 00 05 00 01 00 00 02 01 05 00 00 6c 7e"
    ),
)


def configuration():
    devices = {
        SENSOR: {
            "name": "Motion", "mesh_id": 5,
            "switch_id": MOTION_SWITCH, "MOTION": True,
        },
        LAMP: {
            "name": "Lamp", "mesh_id": 17,
            "switch_id": LIGHT_SWITCH, "MOTION": False,
        },
        TRAP: {
            "name": "Mesh255Sentinel", "mesh_id": 255,
            "switch_id": MOTION_SWITCH, "MOTION": False,
        },
    }
    home_devices = [""] * 256
    for device_id, info in devices.items():
        info.update(ONOFF=True, BRIGHTNESS=True, home_name="Fixture", room="")
        home_devices[info["mesh_id"]] = device_id
    return {
        "cync_credentials": [0x13, 0, 0, 0, 0],
        "cync_config": {
            "devices": devices,
            "rooms": {},
            "home_devices": {HOME: home_devices},
            "home_controllers": {HOME: [int(MOTION_SWITCH), int(LIGHT_SWITCH)]},
            "switchID_to_homeID": {MOTION_SWITCH: HOME, LIGHT_SWITCH: HOME},
        },
    }


class FakeReader:
    def __init__(self, packets):
        self.chunks = [b"\x18\x00\x00\x00\x02\x00\x00", *packets]

    async def read(self, _n=-1):
        return self.chunks.pop(0) if self.chunks else b""


class FakeWriter:
    def __init__(self):
        self.writes = []

    def write(self, packet):
        self.writes.append(bytes(packet))

    async def drain(self):
        pass


class ErrorCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.errors = []

    def emit(self, record):
        self.errors.append(type(record.msg).__name__)


class MotionReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Import the parser directly, bypassing the Home Assistant package entrypoint.
        spec = importlib.util.spec_from_file_location("cync_motion_report_test", HUB_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.errors = ErrorCounter()
        logger = self.module._LOGGER
        self.addCleanup(setattr, logger, "handlers", logger.handlers[:])
        self.addCleanup(setattr, logger, "propagate", logger.propagate)
        logger.handlers = [self.errors]
        logger.propagate = False
        self.motion_events, self.light_events = [], []

    async def replay(self, packets, data=None):
        hub = self.module.CyncHub(
            data or configuration(), {"switches": [], "rooms": []}, lambda: None
        )
        hub.loop = asyncio.get_running_loop()
        hub.reader = FakeReader(packets)
        hub.writer = FakeWriter()
        for device_id, sensor in hub.cync_motion_sensors.items():
            sensor.register(
                lambda d=device_id, s=sensor: self.motion_events.append((d, s.motion))
            )
        for device_id, light in hub.cync_switches.items():
            light.register(
                lambda d=device_id, s=light: self.light_events.append(
                    (d, s.power_state, s.brightness)
                )
            )
        with self.assertRaises(self.module.LostConnection):
            await hub._read_tcp_messages()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.errors.errors, [])
        return hub

    async def test_public_motion_on_off_reaches_sensor_not_mesh255_light(self):
        hub = await self.replay([MOTION_ON, MOTION_OFF])
        self.assertEqual(self.motion_events, [(SENSOR, True), (SENSOR, False)])
        self.assertFalse(self.light_events)
        self.assertFalse(hub.cync_motion_sensors[SENSOR].motion)

    async def test_public_light_capture_preserves_state_brightness_without_motion(self):
        hub = await self.replay([LIGHT])
        self.assertFalse(self.motion_events)
        self.assertEqual(self.light_events, [(LAMP, True, 28)])
        self.assertEqual(hub.cync_switches[LAMP].color_temp, 24)

    async def test_coalesced_motion_light_motion_frames_advance_correctly(self):
        await self.replay([MOTION_ON + LIGHT + MOTION_OFF])
        self.assertEqual(self.motion_events, [(SENSOR, True), (SENSOR, False)])
        self.assertEqual(self.light_events, [(LAMP, True, 28)])

    async def test_existing_fa54_capture_still_publishes_and_acknowledges(self):
        hub = await self.replay([FA54])
        self.assertEqual(self.motion_events, [(SENSOR, True)])
        self.assertFalse(self.light_events)
        self.assertEqual(len(hub.writer.writes), 2)  # Synthetic login plus normal ACK.
        self.assertEqual(hub.writer.writes[-1][0:5], b"\x73\x00\x00\x00\x07")

    async def test_unknown_outer_switch_does_not_require_home_mapping(self):
        unknown = bytearray(MOTION_ON)
        unknown[5:9] = (0x090A0B0C).to_bytes(4, "big")
        await self.replay([bytes(unknown)])
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_multiple_motion_sensors_for_controller_are_rejected(self):
        data = configuration()
        devices = data["cync_config"]["devices"]
        devices[OTHER_SENSOR] = copy.deepcopy(devices[SENSOR])
        devices[OTHER_SENSOR]["mesh_id"] = 6
        data["cync_config"]["home_devices"][HOME][6] = OTHER_SENSOR
        await self.replay([MOTION_ON, MOTION_OFF], data)
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_controller_with_no_motion_capability_does_not_update_mesh255(self):
        data = configuration()
        data["cync_config"]["devices"][SENSOR]["MOTION"] = False
        await self.replay([MOTION_ON, MOTION_OFF], data)
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_invalid_flags_do_not_update_motion_or_mesh255(self):
        packets = []
        for flag in (2, 0x7e, 0xff):
            packet = bytearray(MOTION_ON)
            packet[16] = flag
            packets.append(bytes(packet))
        await self.replay(packets)
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_other_motion_record_lengths_are_consumed_without_light_updates(self):
        payload = MOTION_ON[5:]
        packets = [frame(0x43, payload[:n]) for n in (10, 11, 12, 25)]
        packets += [frame(0x43, payload + b"\0"), frame(0x43, payload + b"\0" * 19)]
        await self.replay(packets)
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_truncated_frame_is_not_published(self):
        await self.replay([MOTION_ON[:-1]])
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)

    async def test_wrong_outer_envelope_is_not_motion(self):
        packet = bytearray(MOTION_ON)
        packet[11] = 7
        await self.replay([bytes(packet)])
        self.assertFalse(self.motion_events)
        self.assertFalse(self.light_events)


if __name__ == "__main__":
    unittest.main()
