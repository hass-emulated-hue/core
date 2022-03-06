"""Controllers for emulated_hue."""
import asyncio
from dataclasses import dataclass

from . import scheduler
from .homeassistant import HomeAssistantController
from .scheduler import add_scheduler, remove_scheduler  # noqa


@dataclass
class Controller:
    """Dataclass to store controller instances."""

    controller_hass: HomeAssistantController | None = None
    loop: asyncio.AbstractEventLoop | None = None


ctl = Controller()


async def async_start(url, token) -> None:
    """Initialize all controllers."""
    ctl.loop = asyncio.get_event_loop()
    # the HA client is initialized in the async_start because it needs a running loop
    ctl.controller_hass = HomeAssistantController(url=url, token=token)
    await ctl.controller_hass.connect()


async def async_stop() -> None:
    """Shutdown all controllers."""
    await scheduler.async_stop()
    await ctl.controller_hass.disconnect()
