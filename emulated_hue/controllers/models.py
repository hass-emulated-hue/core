from pydantic import BaseModel
from emulated_hue import const


class DeviceState(BaseModel):
    power_state: bool
    brightness: int | None = None
    color_temp: int | None = None
    hue: int | None = None
    saturation: int | None = None
    # xy: list | None = None

    def to_hass_data(self):
        data = {}
        if self.brightness:
            data[const.HASS_ATTR_BRIGHTNESS] = self.brightness
        if self.color_temp:
            data[const.HASS_ATTR_COLOR_TEMP] = self.color_temp
        if self.hue and self.saturation:
            data[const.HASS_ATTR_HS_COLOR] = (self.hue, self.saturation)
        return data
