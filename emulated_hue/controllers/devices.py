"""Collection of devices controllable by Hue."""
import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from emulated_hue import const
from emulated_hue.const import ENTERTAINMENT_UPDATE_STATE_UPDATE_RATE
from emulated_hue.utils import clamp

from .models import ALL_STATES, Controller, EntityState

LOGGER = logging.getLogger(__name__)

__device_cache: dict[str, tuple["OnOffDevice", Callable]] = {}

TYPE_ON_OFF = "on_off"
TYPE_BRIGHTNESS = "brightness"
TYPE_RGB = "rgb"
TYPE_COLOR_TEMP = "color_temp"
TYPE_RGBW = "rgbw"
TYPE_RGBWW = "rgbww"


# TODO: Make hass and config accessible from controller without having to pass it


@dataclass(frozen=True)
class DeviceProperties:
    """A device controllable by Hue."""

    manufacturer: str | None
    model: str | None
    name: str | None
    sw_version: str | None
    unique_id: str | None

    @classmethod
    def from_hass(cls, ctl: Controller, entity_id: str) -> "DeviceProperties":
        """Get device properties from Home Assistant."""
        device_id: str = ctl.controller_hass.get_device_id_from_entity_id(entity_id)
        device_attributes: dict = {}
        if device_id:
            device_attributes = ctl.controller_hass.get_device_attributes(device_id)

        unique_id: str | None = None
        if identifiers := device_attributes.get("identifiers"):
            if isinstance(identifiers, dict):
                # prefer real zigbee address if we have that
                # might come in handy later when we want to
                # send entertainment packets to the zigbee mesh
                for key, value in identifiers:
                    if key == "zha":
                        unique_id = value
            elif isinstance(identifiers, list):
                # simply grab the first available identifier for now
                # may inprove this in the future
                for identifier in identifiers:
                    if isinstance(identifier, list):
                        unique_id = identifier[-1]
                        break
                    elif isinstance(identifier, str):
                        unique_id = identifier
                        break
        return cls(
            device_attributes.get("manufacturer"),
            device_attributes.get("model"),
            device_attributes.get("name"),
            device_attributes.get("sw_version"),
            unique_id,
        )


class OnOffDevice:
    """OnOffDevice class."""

    def __init__(
        self,
        ctl: Controller,
        light_id: str,
        entity_id: str,
        config: dict,
        hass_state_dict: dict,
    ):
        """Initialize OnOffDevice."""
        self.ctl: Controller = ctl
        self._light_id: str = light_id
        self._entity_id: str = entity_id

        self._device = DeviceProperties.from_hass(
            self.ctl, entity_id
        )  # Device attributes

        self._hass_state_dict: dict = hass_state_dict  # state from Home Assistant

        self._config: dict = config
        self._name: str = self._config.get("name", "")
        self._unique_id: str = self._config.get("uniqueid", "")
        self._enabled: bool = self._config.get("enabled")

        # throttling
        self._throttle_ms: int = self._config.get("throttle", 0)
        self._last_update: float = datetime.now().timestamp()
        self._default_transition: float = const.DEFAULT_TRANSITION_SECONDS
        if self._throttle_ms > self._default_transition:
            self._default_transition = self._throttle_ms / 1000

        self._hass_state: None | EntityState = None  # EntityState from Home Assistant
        # Latest state and stored in config
        self._config_state: EntityState = EntityState.from_config(
            self._config.get("state")
        )
        self._last_state_update: float = datetime.now().timestamp()

    def __repr__(self):
        """Return representation of object."""
        return f"<{self.__class__.__name__}({self.entity_id})>"

    class OnOffControl:
        """Control on/off state."""

        def __init__(self, device):
            """Initialize OnOffControl."""
            self._device = device  # type: RGBWWDevice
            self._throttle_ms: int = self._device.throttle_ms
            self._control_state = EntityState(
                power_state=self._device.power_state,
                transition_seconds=self._device.transition_seconds,
            )

        @property
        def control_state(self) -> EntityState:
            """Return control state."""
            return self._control_state

        def set_transition_ms(
            self, transition_ms: float, respect_throttle: bool = False
        ) -> None:
            """Set transition in milliseconds."""
            if respect_throttle and transition_ms < self._throttle_ms:
                transition_ms = self._throttle_ms
            self._control_state.transition_seconds = transition_ms / 1000

        def set_transition_seconds(
            self, transition_seconds: float, respect_throttle: bool = False
        ) -> None:
            """Set transition in seconds."""
            self.set_transition_ms(transition_seconds * 1000, respect_throttle)

        def set_power_state(self, power_state: bool) -> None:
            """Set power state."""
            self._control_state.power_state = power_state

        async def async_execute(self) -> None:
            """Execute control state."""
            await self._device.async_execute(self.control_state)

    async def _async_save_config(self) -> None:
        """Save config to file."""
        await self.ctl.config_instance.async_set_storage_value(
            "lights", self._light_id, self._config
        )

    def _save_config(self) -> None:
        """Save config to file."""
        asyncio.create_task(self._async_save_config())

    async def _async_update_config_states(
        self, control_state: EntityState | None = None
    ) -> None:
        """Update config states."""
        for state in ALL_STATES:
            # prioritize our last command if exists, then hass then last saved state
            if control_state and getattr(control_state, state) is not None:
                best_value = getattr(control_state, state)
            elif self._hass_state and getattr(self._hass_state, state) is not None:
                best_value = getattr(self._hass_state, state)
            else:
                best_value = self._config.get("state", {}).get(state, None)
            setattr(self._config_state, state, best_value)

        self._config["state"] = dict(self._config_state)
        await self._async_save_config()

    def _update_device_state(
        self, existing_state: EntityState | None = None
    ) -> EntityState:
        """Update EntityState object with hass state."""
        if existing_state:
            existing_state.power_state = (
                self._hass_state_dict["state"] == const.HASS_STATE_ON
            )
            existing_state.reachable = (
                self._hass_state_dict["state"] != const.HASS_STATE_UNAVAILABLE
            )
            return existing_state
        return EntityState(
            power_state=self._hass_state_dict["state"] == const.HASS_STATE_ON,
            reachable=self._hass_state_dict["state"] != const.HASS_STATE_UNAVAILABLE,
        )

    async def _async_update_allowed(self, control_state: EntityState) -> bool:
        """Check if update is allowed using basic throttling, only update every throttle_ms."""
        # if wanted state is equal to the current state, dont change
        if self._config_state == control_state:
            return False

        if self._throttle_ms is None or self._throttle_ms == 0:
            return True

        # if the last update was less than the throttle time ago, dont change
        now_timestamp = datetime.now().timestamp()
        if now_timestamp - self._last_update < self._throttle_ms / 1000:
            return False

        self._last_update = now_timestamp
        return True

    @property
    def throttle_ms(self) -> int:
        """Return throttle_ms."""
        return self._throttle_ms

    @property
    def enabled(self) -> bool:
        """Return enabled state."""
        return self._enabled

    @property
    def device_properties(self) -> DeviceProperties:
        """Return device object."""
        return self._device

    @property
    def unique_id(self) -> str:
        """Return hue unique id."""
        return self.device_properties.unique_id or self._unique_id

    @property
    def name(self) -> str:
        """Return device name, prioritizing local config."""
        return self._name or self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            "friendly_name"
        )

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        self._save_config()

    @property
    def light_id(self) -> str:
        """Return light id."""
        return self._light_id

    @property
    def entity_id(self) -> str:
        """Return entity id."""
        return self._entity_id

    @property
    def reachable(self) -> bool:
        """Return if device is reachable."""
        return self._config_state.reachable

    @property
    def power_state(self) -> bool:
        """Return power state."""
        return self._config_state.power_state

    @property
    def transition_seconds(self) -> float:
        """Return transition seconds."""
        return self._config_state.transition_seconds or self._default_transition

    def new_control_state(self) -> OnOffControl:
        """Return new control state."""
        return self.OnOffControl(self)

    async def async_update_state(self) -> None:
        """Update EntityState object with Hass state."""
        # prevent entertainment mode updates to avoid lag
        now_timestamp = datetime.now().timestamp()
        if self.ctl.config_instance.entertainment_active and (
            now_timestamp - self._last_state_update
            < ENTERTAINMENT_UPDATE_STATE_UPDATE_RATE / 1000
        ):
            return

        if self._enabled or not self._config_state:
            self._last_state_update = now_timestamp
            self._hass_state_dict = self.ctl.controller_hass.get_entity_state(
                self._entity_id
            )
            # Cascades up the inheritance chain to update the state
            self._hass_state = self._update_device_state()
            await self._async_update_config_states()

    async def async_execute(self, control_state: EntityState) -> None:
        """Execute control state."""
        if not control_state:
            LOGGER.warning("No state to execute for device %s", self._entity_id)
            return

        if not await self._async_update_allowed(control_state):
            return
        if control_state.power_state:
            await self.ctl.controller_hass.async_turn_on(
                self._entity_id, control_state.to_hass_data()
            )
        else:
            await self.ctl.controller_hass.async_turn_off(self._entity_id)
        await self._async_update_config_states(control_state)


class BrightnessDevice(OnOffDevice):
    """BrightnessDevice class."""

    class BrightnessControl(OnOffDevice.OnOffControl):
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

    def new_control_state(self) -> BrightnessControl:
        """Return new control state."""
        return self.BrightnessControl(self)

    # Override
    async def _async_update_allowed(self, control_state: EntityState) -> bool:
        allowed = await super()._async_update_allowed(control_state)
        if allowed:
            return True

        if (
            control_state.brightness
            and self._config_state.brightness
            and (
                abs(self._config_state.brightness - control_state.brightness)
                > const.BRIGHTNESS_THROTTLE_THRESHOLD
            )
        ):
            return True
        return False

    # Override
    def _update_device_state(
        self, existing_state: EntityState | None = None
    ) -> EntityState:
        """Update EntityState object."""
        existing_state = super()._update_device_state(existing_state)
        existing_state.brightness = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_BRIGHTNESS
        )
        return existing_state

    @property
    def brightness(self) -> int:
        """Return brightness."""
        return self._config_state.brightness or 0

    @property
    def flash_state(self) -> str | None:
        """
        Return flash state.

            :return: flash state, one of "short", "long", None
        """
        return self._config_state.flash_state


class CTDevice(BrightnessDevice):
    """CTDevice class."""

    class CTControl(BrightnessDevice.BrightnessControl):
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

    def new_control_state(self) -> CTControl:
        """Return new control state."""
        return self.CTControl(self)

    # Override
    def _update_device_state(
        self, existing_state: EntityState | None = None
    ) -> EntityState:
        """Update EntityState object."""
        existing_state = super()._update_device_state(existing_state)
        existing_state.color_temp = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_COLOR_TEMP
        )
        existing_state.color_mode = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_COLOR_MODE
        )
        return existing_state

    @property
    def color_mode(self) -> str:
        """Return color mode."""
        return self._config_state.color_mode or const.HASS_ATTR_COLOR_TEMP

    @property
    def min_mireds(self) -> int | None:
        """Return min_mireds from hass."""
        return self._hass_state_dict.get(const.HASS_ATTR, {}).get("min_mireds")

    @property
    def max_mireds(self) -> int | None:
        """Return max_mireds from hass."""
        return self._hass_state_dict.get(const.HASS_ATTR, {}).get("max_mireds")

    @property
    def color_temp(self) -> int:
        """Return color temp."""
        return self._config_state.color_temp or 153


class RGBDevice(BrightnessDevice):
    """RGBDevice class."""

    class RGBControl(BrightnessDevice.BrightnessControl):
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

    def new_control_state(self) -> RGBControl:
        """Return new control state."""
        return self.RGBControl(self)

    # Override
    def _update_device_state(
        self, existing_state: EntityState | None = None
    ) -> EntityState:
        """Update EntityState object."""
        existing_state = super()._update_device_state(existing_state)
        existing_state.hue_saturation = self._hass_state_dict.get(
            const.HASS_ATTR, {}
        ).get(const.HASS_ATTR_HS_COLOR)
        existing_state.xy_color = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_XY_COLOR
        )
        existing_state.rgb_color = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_ATTR_RGB_COLOR
        )
        existing_state.color_mode = self._hass_state_dict.get(const.HASS_ATTR, {}).get(
            const.HASS_COLOR_MODE
        )
        return existing_state

    @property
    def color_mode(self) -> str:
        """Return color mode."""
        return self._config_state.color_mode or const.HASS_COLOR_MODE_XY

    @property
    def hue_sat(self) -> tuple[int, int]:
        """Return hue_saturation."""
        return self._config_state.hue_saturation or (0, 0)

    @property
    def xy_color(self) -> tuple[float, float]:
        """Return xy_color."""
        return self._config_state.xy_color or (0, 0)

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return rgb_color."""
        return self._config_state.rgb_color or (0, 0, 0)

    @property
    def effect(self) -> str | None:
        """Return effect."""
        return self._config_state.effect


class RGBWWDevice(CTDevice, RGBDevice):
    """RGBWWDevice class."""

    class RGBWControl(CTDevice.CTControl, RGBDevice.RGBControl):
        """Control RGBW."""

        # Override
        def set_flash(self, flash: str) -> None:
            """Set flash."""
            if self._device.color_mode == const.HASS_ATTR_COLOR_TEMP:
                return CTDevice.CTControl.set_flash(self, flash)
            else:
                return RGBDevice.RGBControl.set_flash(self, flash)

    def new_control_state(self) -> RGBWControl:
        """Return new control state."""
        return self.RGBWControl(self)

    # Override
    def _update_device_state(
        self, existing_state: EntityState | None = None
    ) -> EntityState:
        """Update EntityState object."""
        existing_state = CTDevice._update_device_state(self, existing_state)
        return RGBDevice._update_device_state(self, existing_state)


async def force_update_all():
    """Force all devices to receive an updated state after entertainment mode ends."""
    tasks = []
    for entity_id in __device_cache:
        tasks.append(__device_cache[entity_id][0].async_update_state())
    await asyncio.gather(*tasks)


async def async_get_device(
    ctl: Controller, entity_id: str
) -> OnOffDevice | BrightnessDevice | CTDevice | RGBDevice | RGBWWDevice:
    """Infer light object type from Home Assistant state and returns corresponding object."""
    if entity_id in __device_cache:
        return __device_cache[entity_id][0]

    light_id: str = await ctl.config_instance.async_entity_id_to_light_id(entity_id)
    config: dict = await ctl.config_instance.async_get_light_config(light_id)

    hass_state_dict = ctl.controller_hass.get_entity_state(entity_id)
    entity_color_modes = hass_state_dict[const.HASS_ATTR].get(
        const.HASS_ATTR_SUPPORTED_COLOR_MODES, []
    )

    def new_device_obj(klass):
        return klass(
            ctl,
            light_id,
            entity_id,
            config,
            hass_state_dict,
        )

    if any(
        color_mode
        in [
            const.HASS_COLOR_MODE_HS,
            const.HASS_COLOR_MODE_XY,
            const.HASS_COLOR_MODE_RGB,
            const.HASS_COLOR_MODE_RGBW,
            const.HASS_COLOR_MODE_RGBWW,
        ]
        for color_mode in entity_color_modes
    ) and any(
        color_mode
        in [
            const.HASS_COLOR_MODE_COLOR_TEMP,
            const.HASS_COLOR_MODE_RGBW,
            const.HASS_COLOR_MODE_RGBWW,
            const.HASS_COLOR_MODE_WHITE,
        ]
        for color_mode in entity_color_modes
    ):
        device_obj = new_device_obj(RGBWWDevice)
    elif any(
        color_mode
        in [
            const.HASS_COLOR_MODE_HS,
            const.HASS_COLOR_MODE_XY,
            const.HASS_COLOR_MODE_RGB,
        ]
        for color_mode in entity_color_modes
    ):
        device_obj = new_device_obj(RGBDevice)
    elif const.HASS_COLOR_MODE_COLOR_TEMP in entity_color_modes:
        device_obj = new_device_obj(CTDevice)
    elif const.HASS_COLOR_MODE_BRIGHTNESS in entity_color_modes:
        device_obj = new_device_obj(BrightnessDevice)
    else:
        device_obj = new_device_obj(OnOffDevice)
    await device_obj.async_update_state()

    # Register callback for state changes
    async def callback(event: str, event_details: Any) -> None:
        await device_obj.async_update_state()

    # Callbacks are registered here but never removed
    remove_callback = ctl.controller_hass.register_state_changed_callback(
        callback, entity_id
    )
    __device_cache[entity_id] = device_obj, remove_callback
    return device_obj
