"""Support for local control of entities by emulating a Philips Hue bridge."""
import asyncio
import logging

from hass_client import HomeAssistant
from zeroconf import InterfaceChoice, ServiceInfo, Zeroconf

from .api import HueApi
from .config import Config
from .upnp import UPNPResponderThread
from .utils import get_ip_pton

LOGGER = logging.getLogger(__name__)


class HueEmulator:
    """Support for local control of entities by emulating a Philips Hue bridge."""

    def __init__(self, data_path: str, hass_url: str, hass_token: str):
        """Create an instance of HueEmulator."""
        self._loop = None
        self._config = Config(self, data_path)
        self._hass = HomeAssistant(url=hass_url, token=hass_token)
        self._api = HueApi(self)
        self._upnp_listener = None

    @property
    def config(self) -> Config:
        """Return the Config instance."""
        return self._config

    @property
    def hass(self) -> HomeAssistant:
        """Return the Home Assistant instance."""
        return self._hass

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the running event loop."""
        return self._loop

    async def async_start(self):
        """Start running the Hue emulation."""
        self._loop = asyncio.get_running_loop()
        await self._hass.async_connect()
        await self._api.async_setup()
        await self._async_setup_discovery()
        # remove legacy light_ids config
        if await self.config.async_get_storage_value("light_ids"):
            await self.config.async_delete_storage_value("light_ids")
        # TODO: periodic search for renamed/deleted entities/areas

    async def async_stop(self):
        """Stop running the Hue emulation."""
        LOGGER.info("Application shutdown")
        if self._upnp_listener:
            self._upnp_listener.stop()
        await self._api.async_stop()

    async def _async_setup_discovery(self) -> None:
        """Make this Emulated bridge discoverable on the network."""
        # https://developers.meethue.com/develop/application-design-guidance/hue-bridge-discovery/
        zeroconf = Zeroconf(interfaces=InterfaceChoice.All)
        self._upnp_listener = UPNPResponderThread(self.config)
        LOGGER.debug("Starting mDNS/uPNP discovery broadcast...")

        def setup_discovery():
            zeroconf_type = "_hue._tcp.local."

            info = ServiceInfo(
                zeroconf_type,
                name=f"Philips Hue - {self.config.bridge_id[-6:]}.{zeroconf_type}",
                addresses=[get_ip_pton()],
                port=80,
                properties={
                    "bridgeid": self.config.bridge_id,
                    "modelid": self.config.definitions["bridge"]["modelid"],
                },
            )
            zeroconf.register_service(info)

        self.loop.run_in_executor(None, setup_discovery)
        self._upnp_listener.start()
