"""Support for local control of entities by emulating a Philips Hue bridge."""
import logging

from emulated_hue.controllers.config import Config

from . import controllers
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
        self._config = Config(self, data_path, http_port, https_port, use_default_ports)
        self._hass_url = hass_url
        self._hass_token = hass_token
        self._web = HueWeb(self)

    @property
    def config(self) -> Config:
        """Return the Config instance."""
        return self._config

    async def async_start(self) -> None:
        """Start running the Hue emulation."""
        await controllers.async_start(self._hass_url, self._hass_token)

        await self._web.async_setup()
        controllers.ctl.loop.create_task(async_setup_discovery(self.config))
        # remove legacy light_ids config
        if await self.config.async_get_storage_value("light_ids"):
            await self.config.async_delete_storage_value("light_ids")

        # TODO: periodic search for renamed/deleted entities/areas

    async def async_stop(self) -> None:
        """Stop running the Hue emulation."""
        LOGGER.info("Application shutdown")
        await controllers.async_stop()
        await self.config.async_stop()
        await self._web.async_stop()
