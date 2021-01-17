"""Experimental support for Hue Entertainment API."""
# https://developers.meethue.com/develop/hue-entertainment/philips-hue-entertainment-api/
import logging
import os
import socket
import time
from contextlib import suppress

from emulated_hue.const import (
    DEFAULT_THROTTLE_MS,
    HASS_ATTR_BRIGHTNESS,
    HASS_ATTR_RGB_COLOR,
    HASS_ATTR_TRANSITION,
    HASS_ATTR_XY_COLOR,
)
from mbedtls import tls

LOGGER = logging.getLogger(__name__)

COLOR_TYPE_RGB = "RGB"
COLOR_TYPE_XY_BR = "XY Brightness"


if os.path.isfile("/usr/local/opt/openssl@1.1/bin/openssl"):
    OPENSSL_BIN = "/usr/local/opt/openssl@1.1/bin/openssl"
elif os.name == "nt":
    OPENSSL_BIN = "C:/Program Files/Git/usr/bin/openssl.exe"
else:
    OPENSSL_BIN = "openssl"


def chunked(size, source):
    """Helpermethod to get chunks of size x from a bytes source."""
    for i in range(0, len(source), size):
        yield source[i : i + size]


def block(callback, *args, **kwargs):
    """Block until error is gone."""
    while True:
        with suppress(tls.WantReadError, tls.WantWriteError):
            return callback(*args, **kwargs)


class EntertainmentAPI:
    """Handle UDP socket for HUE Entertainment (streaming mode)."""

    def __init__(self, hue, group_details, user_details):
        """Initialize the class."""
        self.hue = hue
        self.hass = hue.hass
        self.config = hue.config
        self.group_details = group_details
        self._interrupted = False
        self._socket_daemon = None
        self._timestamps = {}
        self._prev_data = {}
        self._user_details = user_details
        self.hue.loop.run_in_executor(None, self.run)

    def run(self):
        """Run the server."""
        LOGGER.info("Start HUE Entertainment Service on UDP port 2100.")
        # length of each packet is dependent of how many lights we're serving in the group
        num_lights = len(self.group_details["lights"])
        pktsize = 16 + (9 * num_lights)

        srv_conf = tls.DTLSConfiguration(
            ciphers=(
                # PSK Requires the selection PSK ciphers.
                "TLS-ECDHE-PSK-WITH-CHACHA20-POLY1305-SHA256",
                "TLS-RSA-PSK-WITH-CHACHA20-POLY1305-SHA256",
                "TLS-PSK-WITH-CHACHA20-POLY1305-SHA256",
                "TLS-PSK-WITH-AES-128-GCM-SHA256",
            ),
            pre_shared_key_store={
                self._user_details["username"]: self._user_details["clientkey"].encode()
            },
            validate_certificates=False,
        )

        dtls_srv_ctx = tls.ServerContext(srv_conf)
        dtls_srv = dtls_srv_ctx.wrap_socket(
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        port = 2100
        dtls_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dtls_srv.bind(("0.0.0.0", port))
        self._dtls_srv = dtls_srv

        conn, addr = dtls_srv.accept()
        conn.setcookieparam(addr[0].encode())
        with suppress(tls.HelloVerifyRequest):
            block(conn.do_handshake)
        conn, addr = conn.accept()
        conn.setcookieparam(addr[0].encode())
        block(conn.do_handshake)

        while not self._interrupted:
            data = conn.recv(pktsize)
            LOGGER.debug(data)
            # Once the client starts streaming, it will pass in packets
            # at a rate between 25 and 50 packets per second !
            color_space = COLOR_TYPE_RGB if data[14] == 0 else COLOR_TYPE_XY_BR
            lights_data = data[16:]
            # issue command to all lights
            for light_data in chunked(9, lights_data):
                self.hue.loop.create_task(
                    self.__async_process_light_packet(light_data, color_space)
                )

    def stop(self):
        """Stop the Entertainment service."""
        self._interrupted = True
        if self._dtls_srv:
            self._dtls_srv.close()
        LOGGER.info("HUE Entertainment Service stopped.")

    async def __async_process_light_packet(self, light_data, color_space):
        """Process an incoming stream message."""
        light_id = str(light_data[1] + light_data[2])
        light_conf = await self.config.async_get_light_config(light_id)

        # throttle command to light
        # TODO: can we pass the raw entertainment message as unicast message on ZHA ?
        # TODO: can we send udp messages to supported lights such as esphome ?
        # For now we simply unpack the entertainment packet and forward
        # individual commands to lights by calling hass services.
        throttle_ms = light_conf.get("throttle", DEFAULT_THROTTLE_MS)
        if not self.__update_allowed(light_id, light_data, throttle_ms):
            return

        entity_id = light_conf["entity_id"]
        svc_data = {"entity_id": entity_id}
        if color_space == COLOR_TYPE_RGB:
            svc_data[HASS_ATTR_RGB_COLOR] = [
                int((light_data[3] * 256 + light_data[4]) / 256),
                int((light_data[5] * 256 + light_data[6]) / 256),
                int((light_data[7] * 256 + light_data[8]) / 256),
            ]
            svc_data[HASS_ATTR_BRIGHTNESS] = sum(svc_data[HASS_ATTR_RGB_COLOR]) / len(
                svc_data[HASS_ATTR_RGB_COLOR]
            )
        else:
            svc_data[HASS_ATTR_XY_COLOR] = [
                float((light_data[3] * 256 + light_data[4]) / 65535),
                float((light_data[5] * 256 + light_data[6]) / 65535),
            ]
            svc_data[HASS_ATTR_BRIGHTNESS] = int(
                (light_data[7] * 256 + light_data[8]) / 256
            )

        # update allowed within throttling, push to light
        if throttle_ms:
            svc_data[HASS_ATTR_TRANSITION] = throttle_ms / 1000
        else:
            svc_data[HASS_ATTR_TRANSITION] = 0
        await self.hass.async_call_service("light", "turn_on", svc_data)
        self.hass.states[entity_id]["attributes"].update(svc_data)

    def __update_allowed(
        self, light_id: str, light_data: bytes, throttle_ms: int
    ) -> bool:
        """Minimalistic form of throttling, only allow updates to a light within a timespan."""

        # check if data changed
        # when not using udp no need to send same light command again
        prev_data = self._prev_data.get(light_id, b"")
        if prev_data == light_data:
            return False
        self._prev_data[light_id] = light_data
        # check throttle timestamp so light commands are only sent once every X milliseconds
        # this is to not overload a light implementation in Home Assistant
        if not throttle_ms:
            return True
        prev_timestamp = self._timestamps.get(light_id, 0)
        cur_timestamp = int(time.time() * 1000)
        if (cur_timestamp - prev_timestamp) >= throttle_ms:
            # change allowed only if within throttle limit
            self._timestamps[light_id] = cur_timestamp
            return True
        return False
