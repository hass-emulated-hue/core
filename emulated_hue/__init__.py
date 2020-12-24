"""Support for local control of entities by emulating a Philips Hue bridge."""
import asyncio
import logging

from hass_client import HomeAssistant

from .api import HueApi
from .config import Config
from .upnp import UPNPResponderThread

_LOGGER = logging.getLogger(__name__)


class HueEmulator:
    """Support for local control of entities by emulating a Philips Hue bridge."""

    def __init__(self, data_path, hass_url, hass_token, ip_address):
        """Create an instance of HueEmulator."""
        self.event_loop = None
        self.config = Config(self, data_path, hass_url, hass_token, ip_address)
        self.hass = HomeAssistant(url=hass_url, token=hass_token)
        self.api = HueApi(self)
        self.upnp_listener = UPNPResponderThread(self.config)

    async def start(self):
        """Start running the Hue emulation."""
        self.event_loop = asyncio.get_running_loop()
        await self.hass.async_connect()
        await self.api.async_setup()
        self.upnp_listener.start()
        # wait for exit
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            _LOGGER.info("Application shutdown")
            self.upnp_listener.stop()
            await self.api.async_stop()
