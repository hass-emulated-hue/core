"""Device state model."""
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from emulated_hue import const

from .homeassistant import HomeAssistantController

if TYPE_CHECKING:
    from .config import Config
else:
    Config = "Config"


@dataclass
class Controller:
    """Dataclass to store controller instances."""

    # Longer names are to be renamed later on
    # here to make refactoring easier
    controller_hass: HomeAssistantController | None = None
    config_instance: Config = None
    loop: asyncio.AbstractEventLoop | None = None


class EntityState(BaseModel):
    """Store device state."""

    power_state: bool = True
    reachable: bool = True
    transition_seconds: float | None = None
    brightness: int | None = None
    color_temp: int | None = None
    hue_saturation: tuple[int, int] | None = None
    xy_color: tuple[float, float] | None = None
    rgb_color: tuple[int, int, int] | None = None
    flash_state: str | None = None
    effect: str | None = None
    color_mode: str | None = None

    def __eq__(self, other):
        """Compare states."""
        other: EntityState = other
        power_state_equal = self.power_state == other.power_state
        brightness_equal = self.brightness == other.brightness
        color_attribute = (
            self._get_color_mode_attribute() == other._get_color_mode_attribute()
        )
        return power_state_equal and brightness_equal and color_attribute

    class Config:
        """Pydantic config."""

        validate_assignment = True

    def _get_color_mode_attribute(self) -> tuple[str, Any] | None:
        """Return color mode and attribute associated."""
        if self.color_mode == const.HASS_COLOR_MODE_COLOR_TEMP:
            return const.HASS_ATTR_COLOR_TEMP, self.color_temp
        elif self.color_mode == const.HASS_COLOR_MODE_HS:
            return const.HASS_ATTR_HS_COLOR, self.hue_saturation
        elif self.color_mode == const.HASS_COLOR_MODE_XY:
            return const.HASS_ATTR_XY_COLOR, self.xy_color
        elif self.color_mode == const.HASS_COLOR_MODE_RGB:
            return const.HASS_ATTR_RGB_COLOR, self.rgb_color
        return None

    def to_hass_data(self) -> dict:
        """Convert to Hass data."""
        data = {}
        if self.brightness:
            data[const.HASS_ATTR_BRIGHTNESS] = self.brightness

        color_mode_attribute = self._get_color_mode_attribute()
        if color_mode_attribute:
            color_mode, attribute = color_mode_attribute
            data[color_mode] = attribute

        if self.effect:
            data[const.HASS_ATTR_EFFECT] = self.effect
        if self.flash_state:
            data[const.HASS_ATTR_FLASH] = self.flash_state
        else:
            data[const.HASS_ATTR_TRANSITION] = self.transition_seconds
        return data

    @classmethod
    def from_config(cls, states: dict | None):
        """Convert from config."""
        # Initialize states if first time running
        if not states:
            return EntityState()

        save_state = {}
        for state in list(vars(cls).get("__fields__")):
            if state in save_state:
                save_state[state] = states[state]
        return EntityState(**save_state)


ALL_STATES: list = list(vars(EntityState).get("__fields__"))
