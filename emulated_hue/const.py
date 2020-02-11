"""Emulated HUE Bridge for HomeAssistant - constants."""
HASS_ATTR_BRIGHTNESS = "brightness"
HASS_ATTR_COLOR_TEMP = "color_temp"
HASS_ATTR_XY_COLOR = "xy_color"
HASS_ATTR_HS_COLOR = "hs_color"
HASS_ATTR_EFFECT = "effect"
HASS_ATTR_TRANSITION = "transition"
HASS_ATTR_FLASH = "flash"

HASS_SUPPORT_BRIGHTNESS = 1
HASS_SUPPORT_COLOR_TEMP = 2
HASS_SUPPORT_EFFECT = 4
HASS_SUPPORT_FLASH = 8
HASS_SUPPORT_COLOR = 16
HASS_SUPPORT_TRANSITION = 32
HASS_SUPPORT_WHITE_VALUE = 128

HASS_ATTR_ENTITY_ID = "entity_id"
HASS_ATTR_SUPPORTED_FEATURES = "supported_features"
HASS_SERVICE_TURN_OFF = "turn_off"
HASS_SERVICE_TURN_ON = "turn_on"
HASS_STATE_OFF = "off"
HASS_STATE_ON = "on"
HASS_STATE_UNAVAILABLE = "unavailable"
HASS_DOMAIN_LIGHT = "light"


# Hue API states
HUE_ATTR_ON = "on"
HUE_ATTR_BRI = "bri"
HUE_ATTR_COLORMODE = "colormode"
HUE_ATTR_HUE = "hue"
HUE_ATTR_SAT = "sat"
HUE_ATTR_CT = "ct"
HUE_ATTR_XY = "xy"
HUE_ATTR_EFFECT = "effect"
HUE_ATTR_TRANSITION = "transitiontime"
HUE_ATTR_ALERT = "alert"

# Hue API min/max values - https://developers.meethue.com/develop/hue-api/lights-api/
HUE_ATTR_BRI_MIN = 1  # Brightness
HUE_ATTR_BRI_MAX = 254
HUE_ATTR_HUE_MIN = 0  # Hue
HUE_ATTR_HUE_MAX = 65535
HUE_ATTR_SAT_MIN = 0  # Saturation
HUE_ATTR_SAT_MAX = 254
HUE_ATTR_CT_MIN = 153  # Color temp
HUE_ATTR_CT_MAX = 500

HUE_UNAUTHORIZED_USER = [
    {"error": {"address": "/", "description": "unauthorized user", "type": "1"}}
]
