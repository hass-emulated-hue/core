"""Collection of devices controllable by Hue."""
import logging

from .models import DeviceState
from .homeassistant import HomeAssistantController
from .const import ATTR_ENTITY_ID

LOGGER = logging.getLogger(__name__)


# TODO: Obtain state from HA to store in device state
class OnOffDevice:
    def __init__(self, controller: HomeAssistantController, config: dict):
        self._controller: HomeAssistantController = controller
        self._config: dict = config
        self._entity_id: str = config[ATTR_ENTITY_ID]
        self._state: None | DeviceState = None

    def turn_on(self) -> None:
        self._state = DeviceState(power_state=True)

    def turn_off(self) -> None:
        self._state = DeviceState(power_state=False)

    def execute(self) -> None:
        if self._state:
            if self._state.power_state:
                await self._controller.turn_on(self._entity_id, self._state.to_hass_data())
            else:
                await self._controller.turn_off(self._entity_id, self._state.to_hass_data())
        else:
            LOGGER.warning("No state to execute! Please report this error.")
        self._state = None


class BrightnessDevice(OnOffDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    def set_brightness(self, brightness: int) -> None:
        if not self._state:
            raise AttributeError("Call turn_on/off before setting brightness!")
        self._state.brightness = brightness

class CTDevice(BrightnessDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    def set_color_temperature(self, color_temperature: int) -> None:
        if not self._state:
            raise AttributeError("Call turn_on/off before setting color_temperature!")
        self._state.color_temperature = color_temperature

class RGBDevice(BrightnessDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    def set_hue_sat(self, hue: int, sat: int) -> None:
        if not self._state:
            raise AttributeError("Call turn_on/off before setting hue_sat!")
        self._state.hue = hue
        self._state.sat = sat

class RGBWDevice(RGBDevice, CTDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)
