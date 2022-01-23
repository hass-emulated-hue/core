"""Device state model."""
from pydantic import BaseModel

from emulated_hue import const

POWER_STATE = "power_state"
BRIGHTNESS = "brightness"
COLOR_TEMP = "color_temp"
HUE_SATURATION = "hue_saturation"
XY_COLOR = "xy_color"
FLASH_STATE = "flash_state"

ALL_STATES = [
    POWER_STATE,
    BRIGHTNESS,
    COLOR_TEMP,
    HUE_SATURATION,
    XY_COLOR,
    FLASH_STATE,
]


class DeviceState(BaseModel):
    """Store device state."""

    power_state: bool
    brightness: int | None = None
    color_temp: int | None = None
    hue_saturation: list[int] | None = None
    xy_color: list[float] | None = None
    flash_state: bool = None

    class Config:
        """Pydantic config."""

        validate_assignment = True

    def to_hass_data(self) -> dict:
        """Convert to Hass data."""
        data = {}
        if self.brightness:
            data[const.HASS_ATTR_BRIGHTNESS] = self.brightness
        if self.color_temp:
            data[const.HASS_ATTR_COLOR_TEMP] = self.color_temp
        if self.hue_saturation:
            data[const.HASS_ATTR_HS_COLOR] = self.hue_saturation
        if self.xy_color:
            data[const.HASS_ATTR_XY_COLOR] = self.xy_color
        if self.flash_state:
            data[const.HASS_ATTR_FLASH] = self.flash_state
        return data
