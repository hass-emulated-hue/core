"""Support for local control of entities by emulating a Philips Hue bridge."""
import asyncio
import logging

from . import controllers
from .config import Config
from .controllers import HomeAssistantController
from .discovery import async_setup_discovery
from .web import HueWeb

LOGGER = logging.getLogger(__name__)


class HueEmulator:
    """Support for local control of entities by emulating a Philips Hue bridge."""

    def __init__(
        self,
        data_path: str,
        hass_url: str,
        hass_token: str,
        http_port: int,
        https_port: int,
        use_default_ports: bool,
    ) -> None:
        """Create an instance of HueEmulator."""
        self._loop = None
        self._config = Config(self, data_path, http_port, https_port, use_default_ports)
        self._hass_url = hass_url
        self._hass_token = hass_token
        self._web = HueWeb(self)

        # the HA client is initialized in the async_start because it needs a running loop
        self._controller_hass: HomeAssistantController | None = None

    @property
    def config(self) -> Config:
        """Return the Config instance."""
        return self._config

    @property
    def controller_hass(self) -> HomeAssistantController | None:
        """Return the Home Assistant controller."""
        return self._controller_hass

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the running event loop."""
        return self._loop

    async def async_start(self) -> None:
        """Start running the Hue emulation."""
        self._loop = asyncio.get_running_loop()
        self._controller_hass = HomeAssistantController(
            url=self._hass_url, token=self._hass_token
        )
        await self._controller_hass.connect()

        await self._web.async_setup()
        self.loop.create_task(async_setup_discovery(self.config))
        # remove legacy light_ids config
        if await self.config.async_get_storage_value("light_ids"):
            await self.config.async_delete_storage_value("light_ids")

        # TODO: periodic search for renamed/deleted entities/areas

    async def async_stop(self) -> None:
        """Stop running the Hue emulation."""
        LOGGER.info("Application shutdown")
        await controllers.async_stop()
        await self.config.async_stop()
        await self._controller_hass.disconnect()
        await self._web.async_stop()
