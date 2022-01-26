"""Device state model."""
from typing import TYPE_CHECKING

from pydantic import BaseModel

from emulated_hue import const
from emulated_hue.utils import clamp

if TYPE_CHECKING:
    from .devices import RGBWDevice


class EntityState(BaseModel):
    """Store device state."""

    power_state: bool
    transition_seconds: float | None = None
    brightness: int | None = None
    color_temp: int | None = None
    hue_saturation: tuple[int, int] | None = None
    xy_color: tuple[float, float] | None = None
    rgb_color: tuple[int, int, int] | None = None
    flash_state: str | None = None
    effect: str | None = None
    reachable: bool = True
    color_mode: str | None = None

    class Config:
        """Pydantic config."""

        validate_assignment = True

    def to_hass_data(self) -> dict:
        """Convert to Hass data."""
        data = {}
        if self.brightness:
            data[const.HASS_ATTR_BRIGHTNESS] = self.brightness

        # If somehow we get both ct and rgb, prefer ct
        if self.color_temp:
            data[const.HASS_ATTR_COLOR_TEMP] = self.color_temp
        elif self.hue_saturation:
            data[const.HASS_ATTR_HS_COLOR] = self.hue_saturation
        elif self.xy_color:
            data[const.HASS_ATTR_XY_COLOR] = self.xy_color
        elif self.rgb_color:
            data[const.HASS_ATTR_RGB_COLOR] = self.rgb_color

        if self.effect:
            data[const.HASS_ATTR_EFFECT] = self.effect
        if self.flash_state:
            data[const.HASS_ATTR_FLASH] = self.flash_state
        else:
            data[const.HASS_ATTR_TRANSITION] = self.transition_seconds
        return data

    @classmethod
    def from_config(cls, states: dict):
        """Convert from config."""
        save_state = {}
        for state in list(vars(cls).get("__fields__")):
            save_state[state] = states.get(state, None)
        return EntityState(**save_state)


ALL_STATES: list = list(vars(EntityState).get("__fields__"))


class OnOffControl:
    """Control on/off state."""

    def __init__(self, device):
        """Initialize OnOffControl."""
        self._device = device  # type: RGBWDevice
        self._throttle_ms: int = self._device.throttle_ms
        self._control_state = EntityState(
            power_state=self._device.power_state,
            transition_seconds=self._device.transition_seconds,
        )

    @property
    def control_state(self) -> EntityState:
        """Return control state."""
        return self._control_state

    def set_transition_ms(self, transition_ms: float) -> None:
        """Set transition in milliseconds."""
        if transition_ms < self._throttle_ms:
            transition_ms = self._throttle_ms
        self._control_state.transition_seconds = transition_ms / 1000

    def set_transition_seconds(self, transition_seconds: float) -> None:
        """Set transition in seconds."""
        self.set_transition_ms(transition_seconds * 1000)

    def set_power_state(self, power_state: bool) -> None:
        """Set power state."""
        self._control_state.power_state = power_state


class BrightnessControl(OnOffControl):
    """Control brightness."""

    def set_brightness(self, brightness: int) -> None:
        """Set brightness from 0-255."""
        self._control_state.brightness = int(clamp(brightness, 1, 255))

    def set_flash(self, flash: str) -> None:
        """
        Set flash.

            :param flash: Can be one of "short" or "long"
        """
        self._control_state.flash_state = flash


class CTControl(BrightnessControl):
    """Control color temperature."""

    def set_color_temperature(self, color_temperature: int) -> None:
        """Set color temperature."""
        self._control_state.color_temp = color_temperature
        self._control_state.color_mode = const.HASS_COLOR_MODE_COLOR_TEMP

    # Override
    def set_flash(self, flash: str) -> None:
        """Set flash with color_temp."""
        super().set_flash(flash)
        self.set_color_temperature(self._device.color_temp)


class RGBControl(BrightnessControl):
    """Control RGB."""

    def set_hue_sat(self, hue: int | float, sat: int | float) -> None:
        """Set hue and saturation colors."""
        self._control_state.hue_saturation = (int(hue), int(sat))
        self._control_state.color_mode = const.HASS_COLOR_MODE_HS

    def set_xy(self, x: float, y: float) -> None:
        """Set xy colors."""
        self._control_state.xy_color = (float(x), float(y))
        self._control_state.color_mode = const.HASS_COLOR_MODE_XY

    def set_rgb(self, r: int, g: int, b: int) -> None:
        """Set rgb colors."""
        self._control_state.rgb_color = (int(r), int(g), int(b))
        self._control_state.color_mode = const.HASS_COLOR_MODE_RGB

    # Override
    def set_flash(self, flash: str) -> None:
        """Set flash."""
        super().set_flash(flash)
        # HASS now requires a color target to be sent when flashing
        self.set_hue_sat(self._device.hue_sat[0], self._device.hue_sat[1])

    def set_effect(self, effect: str) -> None:
        """Set effect."""
        self._control_state.effect = effect


class RGBWControl(CTControl, RGBControl):
    """Control RGBW."""

    # Override
    def set_flash(self, flash: str) -> None:
        """Set flash."""
        if self._device.color_mode == const.HASS_ATTR_COLOR_TEMP:
            return CTControl.set_flash(self, flash)
        else:
            return RGBControl.set_flash(self, flash)
