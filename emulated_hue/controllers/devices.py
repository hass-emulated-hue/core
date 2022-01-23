"""Collection of devices controllable by Hue."""
import logging

from .models import DeviceState
from .homeassistant import HomeAssistantController
from emulated_hue.const import HASS_ATTR_ENTITY_ID, HASS_STATE_ON

LOGGER = logging.getLogger(__name__)

# TODO: Obtain state from HA to store in device state
class OnOffDevice:
    def __init__(self, controller: HomeAssistantController, config: dict):
        self._controller: HomeAssistantController = controller
        self._config: dict = config
        self._entity_id: str = config[HASS_ATTR_ENTITY_ID]

        self._hass_state: None | dict = None  # dict with state from Home Assistant
        self._state: None | DeviceState = None  # DeviceState from Home Assistant

        self._control_state: None | DeviceState = None  # Control state

    @property
    def power_state(self) -> bool:
        if not self._state:
            raise AttributeError("Run async_update_state() first")
        return self._state.power_state

    async def async_update_state(self) -> None:
        """Update DeviceState object with Hass state."""
        self._hass_state = await self._controller.async_get_entity_state(self._entity_id)
        self._control_state = DeviceState(power_state=self._hass_state["state"] == HASS_STATE_ON)

    def turn_on(self) -> None:
        self._control_state = DeviceState(power_state=True)

    def turn_off(self) -> None:
        self._control_state = DeviceState(power_state=False)

    async def execute(self) -> None:
        if self._control_state:
            if self._control_state.power_state:
                await self._controller.async_turn_on(self._entity_id, self._control_state.to_hass_data())
            else:
                await self._controller.async_turn_off(self._entity_id, self._control_state.to_hass_data())
        else:
            LOGGER.warning("No state to execute for device %s", self._entity_id)
        self._control_state = None


class BrightnessDevice(OnOffDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    async def async_update_state(self) -> None:
        """Update DeviceState object with Hass state."""
        await super().async_update_state()
        self._control_state.brightness = self._hass_state["attributes"]["brightness"]

    def set_brightness(self, brightness: int) -> None:
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting brightness!")
        self._control_state.brightness = brightness

class CTDevice(BrightnessDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    def set_color_temperature(self, color_temperature: int) -> None:
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting color_temperature!")
        self._control_state.color_temperature = color_temperature

class RGBDevice(BrightnessDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)

    def set_hue_sat(self, hue: int, sat: int) -> None:
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting hue_sat!")
        self._control_state.hue = hue
        self._control_state.sat = sat

class RGBWDevice(RGBDevice, CTDevice):
    def __init__(self, controller: HomeAssistantController, config: dict):
        super().__init__(controller, config)
