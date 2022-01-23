"""Device state model."""
from pydantic import BaseModel

from emulated_hue import const


class DeviceState(BaseModel):
    """Store device state."""

    power_state: bool
    brightness: int | None = None
    color_temp: int | None = None
    hue_saturation: list[int] | None = None
    xy_color: list[float] | None = None
    rgb_color: list[int] | None = None
    flash_state: str | None = None
    transition_seconds: float = None
    effect: str | None = None
    reachable: bool = True

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
        if self.rgb_color:
            data[const.HASS_ATTR_RGB_COLOR] = self.rgb_color
        if self.flash_state:
            data[const.HASS_ATTR_FLASH] = self.flash_state
        if self.effect:
            data[const.HASS_ATTR_EFFECT] = self.effect
        data[const.HASS_ATTR_TRANSITION] = self.transition_seconds
        return data


ALL_STATES: list = list(vars(DeviceState).get("__fields__"))
