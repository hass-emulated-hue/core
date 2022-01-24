"""Controllers for emulated_hue."""
from . import devices  # noqa
from . import scheduler
from .devices import async_get_device  # noqa
from .homeassistant import HomeAssistantController  # noqa
from .scheduler import add_scheduler, remove_scheduler  # noqa


async def async_start() -> None:
    """Initialize all controllers."""
    pass


async def async_stop() -> None:
    """Shutdown all controllers."""
    await scheduler.async_stop()
