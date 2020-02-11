"""Experimental support for Hue Entertainment API."""
# https://developers.meethue.com/develop/hue-entertainment/philips-hue-entertainment-api/
import asyncio
import logging
import os
import subprocess
import threading
import time

_LOGGER = logging.getLogger(__name__)

NUM_LIGHTS = 3

COLOR_TYPE_RGB = "RGB"
COLOR_TYPE_XY_BR = "XY Brightness"
TIME_THROTTLE = 300


if os.path.isfile("/usr/local/opt/openssl@1.1/bin/openssl"):
    OPENSSL_BIN = "/usr/local/opt/openssl@1.1/bin/openssl"
else:
    OPENSSL_BIN = "openssl"


def chunked(size, source):
    """Helpermethod to get chunks of size x from a bytes source."""
    for i in range(0, len(source), size):
        yield source[i : i + size]


class EntertainmentThread(threading.Thread):
    """Handle UDP socket for HUE Entertainment (streaming mode)."""

    def __init__(self, hue, group_details, user_details):
        """Initialize the class."""
        threading.Thread.__init__(self)
        self.hue = hue
        self.hass = hue.hass
        self.config = hue.config
        self.group_details = group_details
        self._interrupted = False
        self._socket_daemon = None
        self._states = {}
        self._user_details = user_details

    def run(self):
        """Run the server."""
        # MDTLS + PSK is not supported very well in native python
        # As a (temporary) workaround we rely on the OpenSSL executable which is
        # very well supported on all platforms.
        _LOGGER.info("Start HUE Entertainment Service on UDP port 2100.")
        # length of each packet is dependent of how many lights we're serving in the group
        num_lights = len(self.group_details["lights"])
        pktsize = 16 + (9 * num_lights)
        self._socket_daemon = subprocess.Popen(
            [
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
            ],
            stdout=subprocess.PIPE,
        )
        while not self._interrupted:
            data = self._socket_daemon.stdout.read(pktsize)
            if data:
                # Once the client starts streaming, it will pass in packets
                # at a rate between 25 and 50 packets per second !
                self.__process_packet(data)
        _LOGGER.info("HUE Entertainment Service stopped.")

    def stop(self):
        """Stop the Entertainment service."""
        self._interrupted = True
        if self._socket_daemon:
            self._socket_daemon.terminate()
        self.join()

    def __process_packet(self, pkt):
        """Process an incoming stream message."""
        # For now we simply unpack the entertainment packet and forward
        # individual commands to lights by calling hass services.
        # TODO: can we pass the raw entertainment message as unicast message on ZHA ?
        # protocol = pkt[:9].decode()
        # api_version = "%s.%s" % (pkt[9], pkt[10])
        color_space = COLOR_TYPE_RGB if pkt[14] == 0 else COLOR_TYPE_XY_BR
        lights_data = pkt[16:]
        cur_timestamp = int(time.time() * 1000)
        # enumerate light state
        for light_data in chunked(9, lights_data):
            light_id = str(light_data[1] + light_data[2])
            if light_id in self._states:
                cached_state = self._states[light_id]
                entity_id = cached_state["entity_id"]
            else:
                cached_state = {}
                entity_id = asyncio.run_coroutine_threadsafe(
                    self.config.light_id_to_entity_id(light_id), self.hue.event_loop
                ).result()
                cached_state["entity_id"] = entity_id
                self._states[light_id] = cached_state
            svc_data = {"entity_id": entity_id}
            prev_timestamp = cached_state.get("timestamp", 0)
            if color_space == COLOR_TYPE_RGB:
                rgb_color = [
                    int((light_data[3] * 256 + light_data[4]) / 256),
                    int((light_data[5] * 256 + light_data[6]) / 256),
                    int((light_data[7] * 256 + light_data[8]) / 256),
                ]
                prev_rgb = cached_state.get("rgb_color", [0, 0, 0])
                if self.__update_allowed(
                    rgb_color, prev_rgb, cur_timestamp, prev_timestamp
                ):
                    svc_data["rgb_color"] = rgb_color
                    cached_state["rgb_color"] = rgb_color
            else:
                xy_color = [
                    float((light_data[3] * 256 + light_data[4]) / 65535),
                    float((light_data[5] * 256 + light_data[6]) / 65535),
                ]
                brightness = int((light_data[7] * 256 + light_data[8]) / 256)
                prev_xy = cached_state.get("xy_color", [0, 0])
                prev_brightness = cached_state.get("brightness", 0)
                if self.__update_allowed(
                    xy_color, prev_xy, cur_timestamp, prev_timestamp
                ):
                    svc_data["xy_color"] = xy_color
                    cached_state["xy_color"] = xy_color
                if self.__update_allowed(
                    brightness, prev_brightness, cur_timestamp, prev_timestamp
                ):
                    svc_data["brightness"] = brightness
                    cached_state["brightness"] = brightness

            if len(svc_data.keys()) > 1:
                # some details changed, push to light
                cached_state["timestamp"] = cur_timestamp
                svc_data["transition"] = TIME_THROTTLE / 1000
                self.hue.event_loop.create_task(
                    self.hass.call_service("light", "turn_on", svc_data)
                )
                self.hass.states[entity_id]["attributes"].update(svc_data)

    def __update_allowed(self, cur_val, prev_val, cur_timestamp, prev_timestamp):
        """Minimalistic form of throttling, only allow significant changes within a timespan."""
        time_diff = abs(cur_timestamp - prev_timestamp)
        if cur_val == prev_val:
            # value did not change at all, no update needed here
            return False
        elif cur_val != prev_val and time_diff >= TIME_THROTTLE:
            # change allowed only if within throttle limit
            return True
        return False
