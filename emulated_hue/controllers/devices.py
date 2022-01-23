"""Collection of devices controllable by Hue."""
import logging

from emulated_hue import const
from emulated_hue.config import Config

from .homeassistant import HomeAssistantController
from .models import ALL_STATES, DeviceState

LOGGER = logging.getLogger(__name__)


class Device:
    """Instantiate class then await to get the light object."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str | None = None,
        hass_state_dict: dict | None = None,
    ):
        """Initialize Device."""
        self._ctrl_hass: HomeAssistantController = ctrl_hass
        self._ctrl_config: Config = ctrl_config
        self._light_id = light_id
        self._entity_id = entity_id

        self._hass_state_dict: None | dict = (
            hass_state_dict  # state from Home Assistant
        )

    async def _async_get_hass_state(self) -> None:
        """Get state from Home Assistant."""
        self._hass_state_dict = await self._ctrl_hass.async_get_entity_state(
            self._entity_id
        )

    def __await__(
        self,
    ) -> "OnOffDevice|BrightnessDevice|CTDevice|RGBDevice|RGBWDevice":
        """Infer light object type from Home Assistant state and returns corresponding object."""
        config: dict = await self._ctrl_config.async_get_light_config(self._light_id)
        self._entity_id: str = config[const.HASS_ATTR_ENTITY_ID]

        await self._async_get_hass_state()
        entity_color_modes = self._hass_state_dict[const.HASS_ATTR].get(
            const.HASS_ATTR_SUPPORTED_COLOR_MODES, []
        )
        if any(
            color_mode
            in [
                const.HASS_COLOR_MODE_HS,
                const.HASS_COLOR_MODE_XY,
                const.HASS_COLOR_MODE_RGB,
                const.HASS_COLOR_MODE_RGBW,
                const.HASS_COLOR_MODE_RGBWW,
            ]
            for color_mode in entity_color_modes
        ) and any(
            color_mode
            in [
                const.HASS_COLOR_MODE_COLOR_TEMP,
                const.HASS_COLOR_MODE_RGBW,
                const.HASS_COLOR_MODE_RGBWW,
                const.HASS_COLOR_MODE_WHITE,
            ]
            for color_mode in entity_color_modes
        ):
            return RGBWDevice(
                self._ctrl_hass,
                self._ctrl_config,
                self._light_id,
                self._entity_id,
                config,
                self._hass_state_dict,
            )
        elif any(
            color_mode
            in [
                const.HASS_COLOR_MODE_HS,
                const.HASS_COLOR_MODE_XY,
                const.HASS_COLOR_MODE_RGB,
            ]
            for color_mode in entity_color_modes
        ):
            return RGBDevice(
                self._ctrl_hass,
                self._ctrl_config,
                self._light_id,
                self._entity_id,
                config,
                self._hass_state_dict,
            )
        elif const.HASS_COLOR_MODE_COLOR_TEMP in entity_color_modes:
            return CTDevice(
                self._ctrl_hass,
                self._ctrl_config,
                self._light_id,
                self._entity_id,
                config,
                self._hass_state_dict,
            )
        elif const.HASS_COLOR_MODE_BRIGHTNESS in entity_color_modes:
            return BrightnessDevice(
                self._ctrl_hass,
                self._ctrl_config,
                self._light_id,
                self._entity_id,
                config,
                self._hass_state_dict,
            )
        else:
            return OnOffDevice(
                self._ctrl_hass,
                self._ctrl_config,
                self._light_id,
                self._entity_id,
                config,
                self._hass_state_dict,
            )


class OnOffDevice(Device):
    """OnOffDevice class."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize OnOffDevice."""
        super().__init__(ctrl_hass, ctrl_config, light_id, entity_id, hass_state_dict)
        self._config: dict = config

        self._hass_state: None | DeviceState = None  # DeviceState from Home Assistant
        self._control_state: None | DeviceState = None  # Control state

    async def _async_save_config(self) -> None:
        """Save config to file."""
        await self._ctrl_config.async_set_storage_value(
            "lights", self._light_id, self._config
        )

    async def _async_update_config_states(self) -> None:
        """Update config states."""
        save_state = {}
        for state in ALL_STATES:
            # prioritize state from hass, then last command, then last saved state
            best_value = (
                getattr(self._hass_state, state)
                or getattr(self._control_state, state)
                or self._config.get("hass_state", {}).get(state, None)
            )
            save_state[state] = best_value

        self._config["hass_state"] = save_state
        await self._async_save_config()

    @property
    def power_state(self) -> bool:
        """Return power state."""
        if not self._hass_state:
            raise AttributeError("Run async_update_state() first")
        return self._hass_state.power_state

    async def async_update_state(self, update_hass: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        if update_hass:
            await self._async_get_hass_state()
        self._control_state = DeviceState(
            power_state=self._hass_state_dict["state"] == const.HASS_STATE_ON
        )
        await self._async_update_config_states()

    def turn_on(self) -> None:
        """Turn on light."""
        self._control_state = DeviceState(power_state=True)

    def turn_off(self) -> None:
        """Turn off light."""
        self._control_state = DeviceState(power_state=False)

    async def async_execute(self) -> None:
        """Execute control state."""
        if self._control_state:
            if self._control_state.power_state:
                await self._ctrl_hass.async_turn_on(
                    self._entity_id, self._control_state.to_hass_data()
                )
            else:
                await self._ctrl_hass.async_turn_off(
                    self._entity_id, self._control_state.to_hass_data()
                )
        else:
            LOGGER.warning("No state to execute for device %s", self._entity_id)
        await self._async_update_config_states()
        self._control_state = None


class BrightnessDevice(OnOffDevice):
    """BrightnessDevice class."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize BrightnessDevice."""
        super().__init__(
            ctrl_hass, ctrl_config, light_id, entity_id, config, hass_state_dict
        )

    @property
    def brightness(self) -> int:
        """Return brightness."""
        if not self._hass_state:
            raise AttributeError("Run async_update_state() first")
        return self._hass_state.brightness

    async def async_update_state(self, update_hass: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        await super().async_update_state(update_hass)
        self._control_state.brightness = self._hass_state_dict[const.HASS_ATTR][
            const.HASS_ATTR_BRIGHTNESS
        ]

    def set_brightness(self, brightness: int) -> None:
        """Set brightness."""
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting brightness!")
        self._control_state.brightness = brightness


class CTDevice(BrightnessDevice):
    """CTDevice class."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize CTDevice."""
        super().__init__(
            ctrl_hass, ctrl_config, light_id, entity_id, config, hass_state_dict
        )

    @property
    def color_temp(self) -> int:
        """Return color temp."""
        if not self._hass_state:
            raise AttributeError("Run async_update_state() first")
        return self._hass_state.color_temp

    async def async_update_state(self, update_hass: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        await super().async_update_state(update_hass)
        self._control_state.color_temperature = self._hass_state_dict[const.HASS_ATTR][
            const.HASS_ATTR_COLOR_TEMP
        ]

    def set_color_temperature(self, color_temperature: int) -> None:
        """Set color temperature."""
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting color_temperature!")
        self._control_state.color_temperature = color_temperature


class RGBDevice(BrightnessDevice):
    """RGBDevice class."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize RGBDevice."""
        super().__init__(
            ctrl_hass, ctrl_config, light_id, entity_id, config, hass_state_dict
        )

    async def async_update_state(self, update_hass: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        await super().async_update_state(update_hass)
        self._control_state.hue_saturation = self._hass_state_dict[const.HASS_ATTR][
            const.HASS_ATTR_HS_COLOR
        ]
        self._control_state.xy_color = self._hass_state_dict[const.HASS_ATTR][
            const.HASS_ATTR_XY_COLOR
        ]

    def set_hue_sat(self, hue: int, sat: int) -> None:
        """Set hue and saturation colors."""
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting hue_sat!")
        self._control_state.hue_saturation = [int(hue), int(sat)]

    def set_xy(self, x: float, y: float) -> None:
        """Set xy colors."""
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting xy!")
        self._control_state.xy = [float(x), float(y)]


class RGBWDevice(CTDevice, RGBDevice):
    """RGBWDevice class."""

    def __init__(
        self,
        ctrl_hass: HomeAssistantController,
        ctrl_config: Config,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize RGBWDevice."""
        super().__init__(
            ctrl_hass, ctrl_config, light_id, entity_id, config, hass_state_dict
        )

    async def async_update_state(self, update_hass: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        # Prevents overwriting CT values with RGB values
        await CTDevice.async_update_state(self, update_hass)
        await RGBDevice.async_update_state(self, False)
