"""Device state model."""
from pydantic import BaseModel

from emulated_hue import const


class EntityState(BaseModel):
    """Store device state."""

    power_state: bool
    transition_seconds: float
    brightness: int | None = None
    color_temp: int | None = None
    hue_saturation: list[int] | None = None
    xy_color: list[float] | None = None
    rgb_color: list[int] | None = None
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
        if self.color_temp:
            data[const.HASS_ATTR_COLOR_TEMP] = self.color_temp
        if self.hue_saturation:
            data[const.HASS_ATTR_HS_COLOR] = self.hue_saturation
        if self.xy_color:
            data[const.HASS_ATTR_XY_COLOR] = self.xy_color
        if self.rgb_color:
            data[const.HASS_ATTR_RGB_COLOR] = self.rgb_color
        if self.effect:
            data[const.HASS_ATTR_EFFECT] = self.effect
        if self.flash_state:
            data[const.HASS_ATTR_FLASH] = self.flash_state
        else:
            data[const.HASS_ATTR_TRANSITION] = self.transition_seconds
        return data


ALL_STATES: list = list(vars(EntityState).get("__fields__"))
