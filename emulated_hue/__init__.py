"""Support for local control of entities by emulating a Philips Hue bridge."""
import logging

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
        self.ctl: controllers.Controller | None = None
        self._config_vars = (data_path, http_port, https_port, use_default_ports)
        self._hass_url = hass_url
        self._hass_token = hass_token
        self._web: HueWeb | None = None

    async def async_start(self) -> None:
        """Start running the Hue emulation."""
        self.ctl = await controllers.async_start(
            self._hass_url, self._hass_token, *self._config_vars
        )
        self._web = HueWeb(self.ctl)

        await self._web.async_setup()
        self.ctl.loop.create_task(async_setup_discovery(self.ctl.config_instance))
        # remove legacy light_ids config
        if await self.ctl.config_instance.async_get_storage_value("light_ids"):
            await self.ctl.config_instance.async_delete_storage_value("light_ids")

        # TODO: periodic search for renamed/deleted entities/areas

    async def async_stop(self) -> None:
        """Stop running the Hue emulation."""
        LOGGER.info("Application shutdown")
        await controllers.async_stop(self.ctl)
        try:
            await self.ctl.config_instance.async_stop()
            await self._web.async_stop()
        except AttributeError:
            # ctl or _web could be uninitialized if home assistant isn't connected
            pass
