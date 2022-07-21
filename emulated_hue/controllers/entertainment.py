"""Experimental support for Hue Entertainment API."""
# https://developers.meethue.com/develop/hue-entertainment/philips-hue-entertainment-api/
import asyncio
import logging
import os

from emulated_hue.controllers.devices import async_get_device

from .models import Controller

LOGGER = logging.getLogger(__name__)

COLOR_TYPE_RGB = "RGB"
COLOR_TYPE_XY_BR = "XY Brightness"
HASS_SENSOR = "binary_sensor.emulated_hue_entertainment_active"


if os.path.isfile("/usr/local/opt/openssl@1.1/bin/openssl"):
    OPENSSL_BIN = "/usr/local/opt/openssl@1.1/bin/openssl"
elif os.path.isfile("C:/Program Files/Git/usr/bin/openssl.exe"):
    OPENSSL_BIN = "C:/Program Files/Git/usr/bin/openssl.exe"
else:
    OPENSSL_BIN = "openssl"


def chunked(size, source):
    """Helpermethod to get chunks of size x from a bytes source."""
    for i in range(0, len(source), size):
        yield source[i : i + size]


class EntertainmentAPI:
    """Handle UDP socket for HUE Entertainment (streaming mode)."""

    def __init__(self, ctl: Controller, group_details: dict, user_details: dict):
        """Initialize the class."""
        self.ctl: Controller = ctl
        self.group_details = group_details
        self._interrupted = False
        self._socket_daemon = None
        self._timestamps = {}
        self._prev_data = {}
        self._user_details = user_details
        self.ctl.loop.create_task(self.async_run())

        self._pkt_header_begin_size = 9  # HueStream
        self._pkt_header_protocol_size = 7  # protocol version, sequence
        self._pkt_header_uuid_size = 36
        self._pkt_light_data_size = 9 * 20  # 20 channels max
        self._max_pkt_size = (
            self._pkt_header_begin_size
            + self._pkt_header_protocol_size
            + self._pkt_header_uuid_size
            + self._pkt_light_data_size
        )

        num_lights = len(self.group_details["lights"])
        self._likely_pktsize = 16 + (9 * num_lights)

    async def async_run(self):
        """Run the server."""
        # MDTLS + PSK is not supported very well in native python
        # As a (temporary?) workaround we rely on the OpenSSL executable which is
        # very well supported on all platforms.
        LOGGER.info("Start HUE Entertainment Service on UDP port 2100.")
        await self.ctl.controller_hass.set_state(
            HASS_SENSOR, "on", {"room": self.group_details["name"]}
        )
        args = [
            OPENSSL_BIN,
            "s_server",
            "-dtls",
            "-accept",
            "2100",
            "-nocert",
            "-psk_identity",
            self._user_details["username"],
            "-psk",
            self._user_details["clientkey"],
            "-quiet",
        ]
        # NOTE: enable stdin is required for openssl, even if we do not use it.
        self._socket_daemon = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            limit=self._max_pkt_size,
        )
        buffer = b""
        while not self._interrupted:
            # Once the client starts streaming, it will pass in packets
            # at a rate between 25 and 50 packets per second !

            # Prevent buffer overflow, keep 2 packets max
            buffer = buffer[-((self._max_pkt_size + self._pkt_header_begin_size) * 2) :]
            buffer += await self._socket_daemon.stdout.read(self._likely_pktsize)
            pkts = buffer.split(b"HueStream")
            if len(pkts) > 1:
                pkt = None
                for pkt in pkts[:-1]:
                    pkt = b"HueStream" + pkt
                    await self.__process_packet(pkt)
                buffer = pkts[-1]
                # adjust next read to match packet size
                if (guess := len(pkt) - len(buffer)) > 0:
                    self._likely_pktsize = guess

    def stop(self):
        """Stop the Entertainment service."""
        self._interrupted = True
        if self._socket_daemon:
            self._socket_daemon.kill()
        self.ctl.loop.create_task(
            self.ctl.controller_hass.set_state(HASS_SENSOR, "off")
        )
        LOGGER.info("HUE Entertainment Service stopped.")

    async def __process_packet(self, packet: bytes) -> None:
        # Ignore first header message
        if len(packet) < self._pkt_header_begin_size + self._pkt_header_protocol_size:
            return

        version = packet[9]
        color_space = COLOR_TYPE_RGB if packet[14] == 0 else COLOR_TYPE_XY_BR
        lights_data = packet[16:] if version == 1 else packet[52:]
        tasks = []
        # issue command to all lights
        for light_data in chunked(9, lights_data):
            tasks.append(self.__async_process_light_packet(light_data, color_space))
        await asyncio.gather(*tasks)

    async def __async_process_light_packet(self, light_data, color_space):
        """Process an incoming stream message."""
        light_id = str(light_data[1] + light_data[2])
        light_conf = await self.ctl.config_instance.async_get_light_config(light_id)

        # TODO: can we send udp messages to supported lights such as esphome or native ZHA ?
        # For now we simply unpack the entertainment packet and forward
        # individual commands to lights by calling hass services.

        entity_id = light_conf["entity_id"]
        device = await async_get_device(self.ctl, entity_id)
        call = device.new_control_state()
        call.set_power_state(True)
        if color_space == COLOR_TYPE_RGB:
            red = int((light_data[3] * 256 + light_data[4]) / 256)
            green = int((light_data[5] * 256 + light_data[6]) / 256)
            blue = int((light_data[7] * 256 + light_data[8]) / 256)
            call.set_rgb(red, green, blue)
            call.set_brightness(int(sum(call.control_state.rgb_color) / 3))
        else:
            x = float((light_data[3] * 256 + light_data[4]) / 65535)
            y = float((light_data[5] * 256 + light_data[6]) / 65535)
            call.set_xy(x, y)
            call.set_brightness(int((light_data[7] * 256 + light_data[8]) / 256))
        call.set_transition_ms(0, respect_throttle=True)
        await call.async_execute()
