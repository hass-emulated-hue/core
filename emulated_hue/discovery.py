"""Support UPNP discovery method that mimics Hue hubs."""
import asyncio
import logging
import re
import select
import socket
import threading

from zeroconf import InterfaceChoice, ServiceInfo, Zeroconf

from .config import Config
from .utils import Default, get_ip_pton

LOGGER = logging.getLogger(__name__)


async def async_setup_discovery(config: Config) -> None:
    """Make this Emulated bridge discoverable on the network."""
    # https://developers.meethue.com/develop/application-design-guidance/hue-bridge-discovery/
    loop = asyncio.get_running_loop()

    LOGGER.debug("Starting mDNS/uPNP discovery broadcast...")

    # start ssdp discovery
    upnp_listener = UPNPResponderThread(config)
    upnp_listener.start()

    # start mdns/zeroconf discovery
    loop.run_in_executor(None, start_zeroconf_discovery, config)


def start_zeroconf_discovery(config: Config):
    """Start zeroconf discovery."""
    zeroconf = Zeroconf(interfaces=InterfaceChoice.All)
    zeroconf_type = "_hue._tcp.local."

    info = ServiceInfo(
        zeroconf_type,
        name=f"Philips Hue - {config.bridge_id[-6:]}.{zeroconf_type}",
        addresses=[get_ip_pton()],
        port=80,
        properties={
            "bridgeid": config.bridge_id,
            "modelid": config.definitions["bridge"]["basic"]["modelid"],
        },
    )
    zeroconf.register_service(info)


class UPNPResponderThread(threading.Thread):
    """Handle responding to UPNP/SSDP discovery requests."""

    # TODO: Convert to asyncio socket instead of thread

    _interrupted = False

    def __init__(self, config: Config, bind_multicast: bool = True):
        """Initialize the class."""
        threading.Thread.__init__(self)
        self.daemon = True

        self.config = config
        self.ip_addr = config.ip_addr
        self.listen_port = config.http_port
        self.upnp_bind_multicast = bind_multicast

        # Note that the double newline at the end of
        # this string is required per the SSDP spec
        resp_template = """HTTP/1.1 200 OK
CACHE-CONTROL: max-age=60
EXT:
LOCATION: http://{ip_addr}:{port_num}/description.xml
SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.20.0
hue-bridgeid: {bridge_id}
ST: {device_type}
USN: {bridge_uuid}

"""

        self.upnp_device_response = resp_template.format_map(
            Default(
                ip_addr=config.ip_addr,
                port_num=config.http_port,
                bridge_id=config.bridge_id,
                bridge_uuid=f"uuid:{config.bridge_uid}",
            )
        )

    def run(self):
        """Run the server."""
        # Listen for UDP port 1900 packets sent to SSDP multicast address
        ssdp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ssdp_socket.setblocking(False)

        # Required for receiving multicast
        ssdp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        ssdp_socket.setsockopt(
            socket.SOL_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.ip_addr)
        )

        ssdp_socket.setsockopt(
            socket.SOL_IP,
            socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton("239.255.255.250") + socket.inet_aton(self.ip_addr),
        )

        if self.upnp_bind_multicast:
            ssdp_socket.bind(("", 1900))
        else:
            ssdp_socket.bind((self.ip_addr, 1900))

        while True:
            if self._interrupted:
                clean_socket_close(ssdp_socket)
                return

            try:
                read, _, _ = select.select([ssdp_socket], [], [ssdp_socket], 2)

                if ssdp_socket in read:
                    data, addr = ssdp_socket.recvfrom(1024)
                else:
                    # most likely the timeout, so check for interrupt
                    continue
            except socket.error as ex:
                if self._interrupted:
                    clean_socket_close(ssdp_socket)
                    return

                LOGGER.error("UPNP Responder socket exception occurred: %s", ex.__str__)
                # without the following continue, a second exception occurs
                # because the data object has not been initialized
                continue

            decoded_data = data.decode("utf-8", errors="ignore")
            if "M-SEARCH" in decoded_data:
                # SSDP M-SEARCH method received, respond to it with our info
                resp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                decoded_st_field = re.search(
                    "(?<=\\r\\nST: )(.*)(?=\\r)", decoded_data
                ).group(0)
                if decoded_st_field == "ssdp:all":
                    decoded_st_field = "urn:schemas-upnp-org:device:basic:1"
                else:
                    # decoded_st_field = f"uuid:{self.config.bridge_uid}"
                    decoded_st_field = "urn:schemas-upnp-org:device:basic:1"
                response = (
                    self.upnp_device_response.format(device_type=decoded_st_field)
                    .replace("\n", "\r\n")
                    .encode("utf-8")
                )
                resp_socket.sendto(response, addr)
                LOGGER.debug(
                    "Serving SSDP discovery info to %s, received data %s, response data %s",
                    addr,
                    repr(decoded_data),
                    repr(response),
                )
                resp_socket.close()

    def stop(self):
        """Stop the server."""
        # Request for server
        self._interrupted = True
        self.join()


def clean_socket_close(sock):
    """Close a socket connection and logs its closure."""
    LOGGER.info("UPNP responder shutting down.")
    sock.close()
