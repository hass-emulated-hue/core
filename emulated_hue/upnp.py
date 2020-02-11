"""Support UPNP discovery method that mimics Hue hubs."""
import logging
import select
import socket
import threading

_LOGGER = logging.getLogger(__name__)


class UPNPResponderThread(threading.Thread):
    """Handle responding to UPNP/SSDP discovery requests."""

    _interrupted = False

    def __init__(self, config):
        """Initialize the class."""
        threading.Thread.__init__(self)

        self.host_ip_addr = config.host_ip_addr
        self.listen_port = config.http_port
        self.upnp_bind_multicast = True

        # Note that the double newline at the end of
        # this string is required per the SSDP spec
        resp_template = """HTTP/1.1 200 OK
CACHE-CONTROL: max-age=60
EXT:
LOCATION: http://{0}:{1}/description.xml
SERVER: FreeRTOS/6.0.5, UPnP/1.0, IpBridge/0.1
hue-bridgeid: 1234
ST: urn:schemas-upnp-org:device:basic:1
USN: uuid:Socket-1_0-221438K0100073::urn:schemas-upnp-org:device:basic:1

"""

        self.upnp_response = (
            resp_template.format(config.host_ip_addr, config.http_port)
            .replace("\n", "\r\n")
            .encode("utf-8")
        )

    def run(self):
        """Run the server."""
        # Listen for UDP port 1900 packets sent to SSDP multicast address
        ssdp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ssdp_socket.setblocking(False)

        # Required for receiving multicast
        ssdp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        ssdp_socket.setsockopt(
            socket.SOL_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.host_ip_addr)
        )

        ssdp_socket.setsockopt(
            socket.SOL_IP,
            socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton("239.255.255.250") + socket.inet_aton(self.host_ip_addr),
        )

        if self.upnp_bind_multicast:
            ssdp_socket.bind(("", 1900))
        else:
            ssdp_socket.bind((self.host_ip_addr, 1900))

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

                _LOGGER.error(
                    "UPNP Responder socket exception occurred: %s", ex.__str__
                )
                # without the following continue, a second exception occurs
                # because the data object has not been initialized
                continue

            if "M-SEARCH" in data.decode("utf-8", errors="ignore"):
                # SSDP M-SEARCH method received, respond to it with our info
                resp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                resp_socket.sendto(self.upnp_response, addr)
                resp_socket.close()

    def stop(self):
        """Stop the server."""
        # Request for server
        self._interrupted = True
        self.join()


def clean_socket_close(sock):
    """Close a socket connection and logs its closure."""
    _LOGGER.info("UPNP responder shutting down.")

    sock.close()
