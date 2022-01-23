"""Collection of devices controllable by Hue."""
import logging

from .models import DeviceState

LOGGER = logging.getLogger(__name__)

class OnOffDevice:
    def __init__(self, config: dict):
        self._config = config
        self._state: None | DeviceState = None

    def turn_on(self) -> None:
        self._state = DeviceState(power_state=True)

    def turn_off(self) -> None:
        self._state = DeviceState(power_state=False)

    def execute(self) -> None:
        if self._state:
            if self._state.power_state:

            self._state.execute()
        else:
            LOGGER.warning("No state to execute! Please report this error.")
        self._state = None

