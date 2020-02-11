"""Support for local control of entities by emulating a Philips Hue bridge."""
import asyncio
import logging

from .config import Config
from .hass import HomeAssistant
from .hue_api import HueApi
from .upnp import UPNPResponderThread

_LOGGER = logging.getLogger(__name__)


class HueEmulator:
    """Support for local control of entitiesby emulating a Philips Hue bridge."""

    def __init__(self, event_loop, data_path, hass_url, hass_token):
        """Create an instance of HueEmulator."""
        self.event_loop = event_loop
        self.config = Config(self, data_path, hass_url, hass_token)
        self.hass = HomeAssistant(self)
        self.hue_api = HueApi(self)
        self.upnp_listener = UPNPResponderThread(self.config)

    async def start(self):
        """Start running the Hue emulation."""
        await self.hass.async_setup()
        await self.hue_api.async_setup()
        self.upnp_listener.start()
        # wait for exit
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            _LOGGER.info("Application shutdown")
            self.upnp_listener.stop()
            await self.hue_api.stop()
