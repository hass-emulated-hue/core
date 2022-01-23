"""Collection of devices controllable by Hue."""
import logging

from emulated_hue import const
from emulated_hue.config import Config

from .homeassistant import HomeAssistantController
from .models import ALL_STATES, DeviceState

LOGGER = logging.getLogger(__name__)


async def async_get_hass_state(
    ctrl_hass: HomeAssistantController, entity_id: str
) -> dict:
    """Get Home Assistant state for entity."""
    return await ctrl_hass.async_get_entity_state(entity_id)


class OnOffDevice:
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
        self._ctrl_hass: HomeAssistantController = ctrl_hass
        self._ctrl_config: Config = ctrl_config
        self._light_id = light_id
        self._entity_id = entity_id

        self._hass_state_dict: None | dict = (
            hass_state_dict  # state from Home Assistant
        )

        self._config: dict = config

        self._hass_state: None | DeviceState = None  # DeviceState from Home Assistant
        self._control_state: None | DeviceState = None  # Control state
        self._config_state: None | DeviceState = (
            None  # Latest state and stored in config
        )

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
            if self._hass_state and getattr(self._hass_state, state) is not None:
                best_value = getattr(self._hass_state, state)
            elif (
                self._control_state and getattr(self._control_state, state) is not None
            ):
                best_value = getattr(self._control_state, state)
            else:
                best_value = self._config.get("hass_state", {}).get(state, None)
            save_state[state] = best_value

        self._config["hass_state"] = save_state
        self._config_state = DeviceState(**save_state)
        await self._async_save_config()

    @property
    def flash_state(self) -> bool:
        """Return flash state."""
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.flash_state

    @property
    def power_state(self) -> bool:
        """Return power state."""
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.power_state

    async def async_update_state(self, full_update: bool = True) -> None:
        """Update DeviceState object with Hass state."""
        if full_update:
            self._hass_state_dict = await async_get_hass_state(
                self._ctrl_hass, self._entity_id
            )
        # Cascades up the inheritance chain to update the state
        self._update_device_state(full_update)
        await self._async_update_config_states()

    def _update_device_state(self, full_update: bool) -> None:
        """Update DeviceState object."""
        if full_update:
            self._hass_state = DeviceState(
                power_state=self._hass_state_dict["state"] == const.HASS_STATE_ON
            )

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
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.brightness

    def _update_device_state(self, full_update: bool) -> None:
        """Update DeviceState object."""
        super()._update_device_state(full_update)
        self._hass_state.brightness = self._hass_state_dict.get(
            const.HASS_ATTR, {}
        ).get(const.HASS_ATTR_BRIGHTNESS)

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
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.color_temp

    def _update_device_state(self, full_update: bool) -> None:
        """Update DeviceState object."""
        super()._update_device_state(full_update)
        self._hass_state.color_temp = self._hass_state_dict.get(
            const.HASS_ATTR, {}
        ).get(const.HASS_ATTR_COLOR_TEMP)

    def set_color_temperature(self, color_temperature: int) -> None:
        """Set color temperature."""
        if not self._control_state:
            raise AttributeError("Call turn_on/off before setting color_temperature!")
        self._control_state.color_temp = color_temperature


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

    @property
    def hue_saturation(self) -> list[int]:
        """Return hue_saturation."""
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.hue_saturation

    @property
    def xy_color(self) -> list[float]:
        """Return xy_color."""
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.xy_color

    @property
    def rgb_color(self) -> list[int]:
        """Return rgb_color."""
        if not self._config_state:
            raise AttributeError("Run async_update_state() first")
        return self._config_state.rgb_color

    def _update_device_state(self, full_update: bool = True) -> None:
        """Update DeviceState object."""
        super()._update_device_state(full_update)
        self._hass_state.hue_saturation = self._hass_state_dict.get(
            const.HASS_ATTR, {}
        ).get(const.HASS_ATTR_HS_COLOR)
        self._hass_state.xy_color = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_XY_COLOR
        )
        self._hass_state.rgb_color = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_RGB_COLOR
        )

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

    def _update_device_state(self, full_update: bool = True) -> None:
        """Update DeviceState object."""
        CTDevice._update_device_state(self, True)
        RGBDevice._update_device_state(self, False)


async def async_get_device(
    ctrl_hass: HomeAssistantController, ctrl_config: Config, light_id: str
) -> OnOffDevice | BrightnessDevice | CTDevice | RGBDevice | RGBWDevice:
    """Infer light object type from Home Assistant state and returns corresponding object."""
    config: dict = await ctrl_config.async_get_light_config(light_id)
    entity_id: str = config[const.HASS_ATTR_ENTITY_ID]

    hass_state_dict = await async_get_hass_state(ctrl_hass, entity_id)
    entity_color_modes = hass_state_dict[const.HASS_ATTR].get(
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
            ctrl_hass,
            ctrl_config,
            light_id,
            entity_id,
            config,
            hass_state_dict,
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
            ctrl_hass,
            ctrl_config,
            light_id,
            entity_id,
            config,
            hass_state_dict,
        )
    elif const.HASS_COLOR_MODE_COLOR_TEMP in entity_color_modes:
        return CTDevice(
            ctrl_hass,
            ctrl_config,
            light_id,
            entity_id,
            config,
            hass_state_dict,
        )
    elif const.HASS_COLOR_MODE_BRIGHTNESS in entity_color_modes:
        return BrightnessDevice(
            ctrl_hass,
            ctrl_config,
            light_id,
            entity_id,
            config,
            hass_state_dict,
        )
    else:
        return OnOffDevice(
            ctrl_hass,
            ctrl_config,
            light_id,
            entity_id,
            config,
            hass_state_dict,
        )
