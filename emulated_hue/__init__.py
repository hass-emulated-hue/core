"""Support for local control of entities by emulating a Philips Hue bridge."""
import asyncio
import logging

from hass_client import HomeAssistant

from .api import HueApi
from .config import Config
from .discovery import async_setup_discovery

LOGGER = logging.getLogger(__name__)


class HueEmulator:
    """Support for local control of entities by emulating a Philips Hue bridge."""

    def __init__(self, data_path: str, hass_url: str, hass_token: str):
        """Create an instance of HueEmulator."""
        self._loop = None
        self._config = Config(self, data_path)
        self._hass = HomeAssistant(url=hass_url, token=hass_token)
        self._api = HueApi(self)

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
        self.loop.create_task(async_setup_discovery(self.config))
        # remove legacy light_ids config
        if await self.config.async_get_storage_value("light_ids"):
            await self.config.async_delete_storage_value("light_ids")
        # TODO: periodic search for renamed/deleted entities/areas

    async def async_stop(self):
        """Stop running the Hue emulation."""
        LOGGER.info("Application shutdown")
        await self._api.async_stop()
