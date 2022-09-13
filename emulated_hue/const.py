"""Emulated HUE Bridge for HomeAssistant - constants."""

# Prevent overloading home assistant / implementation
# Will not be respected when using udp
DEFAULT_THROTTLE_MS = 150
BRIGHTNESS_THROTTLE_THRESHOLD = 255 / 4
ENTERTAINMENT_UPDATE_STATE_UPDATE_RATE = 1000

CONFIG_WRITE_DELAY_SECONDS = 10

DEFAULT_TRANSITION_SECONDS = 0.4

HASS_ATTR_BRIGHTNESS = "brightness"
HASS_ATTR_COLOR_TEMP = "color_temp"
HASS_ATTR_XY_COLOR = "xy_color"
HASS_ATTR_HS_COLOR = "hs_color"
HASS_ATTR_RGB_COLOR = "rgb_color"
HASS_ATTR_EFFECT = "effect"
HASS_ATTR_TRANSITION = "transition"
HASS_ATTR_FLASH = "flash"

# Deprecated Bitfield features
HASS_SUPPORT_BRIGHTNESS = 1
HASS_SUPPORT_COLOR_TEMP = 2
HASS_SUPPORT_EFFECT = 4  # unused
HASS_SUPPORT_FLASH = 8  # unused
HASS_SUPPORT_COLOR = 16
HASS_SUPPORT_TRANSITION = 32  # unused
HASS_SUPPORT_WHITE_VALUE = 128  # unused

# New color modes
# https://github.com/home-assistant/core/blob/2b3148296c7af2dd381b48bd6c5aa2af5fdfac1b/homeassistant/components/light/__init__.py#L55
HASS_COLOR_MODE = "color_mode"
HASS_COLOR_MODE_UNKNOWN = "unknown"  # Ambiguous color mode
HASS_COLOR_MODE_ONOFF = "onoff"  # Must be the only supported mode
HASS_COLOR_MODE_BRIGHTNESS = "brightness"  # Must be the only supported mode
HASS_COLOR_MODE_COLOR_TEMP = "color_temp"
HASS_COLOR_MODE_HS = "hs"
HASS_COLOR_MODE_XY = "xy"
HASS_COLOR_MODE_RGB = "rgb"
HASS_COLOR_MODE_RGBW = "rgbw"
HASS_COLOR_MODE_RGBWW = "rgbww"
HASS_COLOR_MODE_WHITE = "white"  # Must *NOT* be the only supported mode

HASS_ATTR = "attributes"
HASS_ATTR_ENTITY_ID = "entity_id"
HASS_ATTR_SUPPORTED_FEATURES = "supported_features"
HASS_ATTR_SUPPORTED_COLOR_MODES = "supported_color_modes"
HASS_SERVICE_TURN_OFF = "turn_off"
HASS_SERVICE_TURN_ON = "turn_on"
HASS_STATE_OFF = "off"
HASS_STATE_ON = "on"
HASS_STATE_UNAVAILABLE = "unavailable"
HASS_DOMAIN_LIGHT = "light"

HASS_ATTR_BRI_MIN = 1  # Brightness

# Hue API states
HUE_ATTR_ON = "on"
HUE_ATTR_BRI = "bri"
HUE_ATTR_COLORMODE = "colormode"
HUE_ATTR_HUE = "hue"
HUE_ATTR_SAT = "sat"
HUE_ATTR_CT = "ct"
HUE_ATTR_HS = "hs"
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

HASS = "hass"
HUE = "hue"

HUE_HTTP_PORT = 80
HUE_HTTPS_PORT = 443

# New const
HASS_DOMAIN_HOMEASSISTANT = "homeassistant"
HASS_DOMAIN_PERSISTENT_NOTIFICATION = "persistent_notification"
HASS_SERVICE_PERSISTENT_NOTIFICATION_CREATE = "create"
HASS_SERVICE_PERSISTENT_NOTIFICATION_DISMISS = "dismiss"
