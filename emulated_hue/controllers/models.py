from pydantic import BaseModel


class DeviceState(BaseModel):
    power_state: bool
    brightness: int | None = None

    def to_homeassistant_service_data(self):
        data = {}
        if self.brightness:
            data['brightness'] = self.brightness
        return data
