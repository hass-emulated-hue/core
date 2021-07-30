"""Emulated HUE Bridge for HomeAssistant - constants."""
from enum import Enum

DEFAULT_THROTTLE_MS = 0


class HASS_ATTR(Enum):
    """Defines light attribute constants for HASS."""

    NAME = "attributes"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"
    XY_COLOR = "xy_color"
    HS_COLOR = "hs_color"
    RGB_COLOR = "rgb_color"
    EFFECT = "effect"
    TRANSITION = "transition"
    FLASH = "flash"
    ENTITY_ID = "entity_id"
    SUPPORTED_FEATURES = "supported_features"
    SUPPORTED_COLOR_MODES = "supported_color_modes"
    BRI_MIN = 1  # Brightness


class HASS_SUPPORT(Enum):
    """Unused deprecated Bitfield features."""
    BRIGHTNESS = 1
    COLOR_TEMP = 2
    EFFECT = 4  # unused
    FLASH = 8  # unused
    COLOR = 16
    TRANSITION = 32  # unused
    WHITE_VALUE = 128  # unused


# New color modes
# https://github.com/home-assistant/core/blob/2b3148296c7af2dd381b48bd6c5aa2af5fdfac1b/homeassistant/components/light/__init__.py#L55
class HASS_COLOR_MODE(Enum):
    """Possible values from HASS for color_mode."""
    UNKNOWN = "unknown"  # Ambiguous color mode
    ONOFF = "onoff"  # Must be the only supported mode
    BRIGHTNESS = "brightness"  # Must be the only supported mode
    COLOR_TEMP = "color_temp"
    HS = "hs"
    XY = "xy"
    RGB = "rgb"
    RGBW = "rgbw"
    RGBWW = "rgbww"
    WHITE = "white"  # Must *NOT* be the only supported mode


class HASS_SERVICE(Enum):
    """HASS service calls."""
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class HASS_STATE(Enum):
    """Possible state values from HASS."""
    OFF = "off"
    ON = "on"
    UNAVAILABLE = "unavailable"


class HASS_DOMAIN(Enum):
    """HASS entity domains."""
    LIGHT = "light"


class HUE_ATTR(Enum):
    """HUE light attributes."""
    # Hue API states
    ON = "on"
    BRI = "bri"
    COLORMODE = "colormode"
    HUE = "hue"
    SAT = "sat"
    CT = "ct"
    HS = "hs"
    XY = "xy"
    EFFECT = "effect"
    TRANSITION = "transitiontime"
    ALERT = "alert"

    # Hue API min/max values - https://developers.meethue.com/develop/hue-api/lights-api/
    BRI_MIN = 1  # Brightness
    BRI_MAX = 254
    HUE_MIN = 0  # Hue
    HUE_MAX = 65535
    SAT_MIN = 0  # Saturation
    SAT_MAX = 254
    CT_MIN = 153  # Color temp
    CT_MAX = 500


class HASS(Enum):
    """All HASS enums."""
    NAME = "hass"
    ATTR = HASS_ATTR
    COLOR_MODE = HASS_COLOR_MODE  # type: HASS_COLOR_MODE
    SUPPORT = HASS_SUPPORT  # type: HASS_SUPPORT
    SERVICE = HASS_SERVICE  # type: HASS_SERVICE
    STATE = HASS_STATE  # type: HASS_STATE
    DOMAIN = HASS_DOMAIN  # type: HASS_DOMAIN


class HUE(Enum):
    """All Hue enums"""
    NAME = "hue"
    ATTR = HUE_ATTR  # type: HUE_ATTR


class SystemType(Enum):
    """Main entrypoint for const."""
    HASS = HASS  # type: HASS
    HUE = HUE  # type: HUE
