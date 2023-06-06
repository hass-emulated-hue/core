"""Controllers for emulated_hue."""
import asyncio

from . import scheduler
from .config import Config
from .homeassistant import HomeAssistantController
from .scheduler import add_scheduler, remove_scheduler  # noqa


async def async_start(
    url, token, data_path, http_port, https_port, use_default_ports
) -> Config:
    """Initialize all controllers."""
    loop = asyncio.get_event_loop()
    # the HA client is initialized in the async_start because it needs a running loop
    controller_hass = HomeAssistantController(url=url, token=token)
    cfg = Config(
        controller_hass, loop, data_path, http_port, https_port, use_default_ports
    )
    await cfg.controller_hass.connect()
    return cfg


async def async_stop(ctl: Config) -> None:
    """Shutdown all controllers."""
    await scheduler.async_stop()
    try:
        await ctl.controller_hass.disconnect()
    except AttributeError:
        # controller_hass is not initialized if home assistant isn't connected
        pass
