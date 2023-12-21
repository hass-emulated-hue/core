"""Support for a Hue API to control Home Assistant."""
import functools
import logging
import uuid
import tzlocal
import asyncio
import json

from aiohttp import web
from aiohttp_sse import sse_response
from emulated_hue import api, controllers, const
from emulated_hue.const import UUID_NAMESPACES
from emulated_hue.controllers import Controller
from emulated_hue.controllers.devices import async_get_device
from emulated_hue.utils import (
    ClassRouteTableDef,
    send_error_response, send_json_response_v2,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
else:
    HueEmulator = "HueEmulator"

LOGGER = logging.getLogger(__name__)


def authorizev2(check_user=True, log_request=True):
    """Run some common logic to log and validate all requests (used as a decorator)."""

    def func_wrapper(func):
        @functools.wraps(func)
        async def wrapped_func(cls: "HueApiV2Endpoints", request: web.Request):
            if log_request:
                LOGGER.debug("[%s] %s %s", request.remote, request.method, request.path)
            # check username

            if check_user:
                username = request.headers.get("hue-application-key")
                if not username or not await cls.ctl.config_instance.async_get_user(
                        username
                ):
                    path = request.path.replace(username, "")
                    LOGGER.debug("[%s] Invalid username (api key)", request.remote)
                    return send_error_response(path, "unauthorized user", 1)

            # check and unpack (json) body if needed
            if request.can_read_body:
               try:
                   request_data = await request.text()
                   # clean request_data for weird apps like f.lux
                   request_data = request_data.rstrip("\x00")
                   request_data = json.loads(request_data)
               except ValueError:
                   LOGGER.warning("Invalid json in request: %s --> %s", request)
                   return send_error_response("", "body contains invalid json", 2)
               return await func(cls, request, request_data)
            return await func(cls, request)

        return wrapped_func

    return func_wrapper


# pylint: disable=invalid-name
routes = ClassRouteTableDef()


# pylint: enable=invalid-name


class HueApiV2Endpoints(api.HueApiEndpoints):
    """Hue API v2 endpoints."""

    def __init__(self, ctl: Controller):
        """Initialize the v1 api."""
        super().__init__(ctl)

    @property
    def route(self):
        """Return routes for external access."""
        if not len(routes):
            routes.add_manual_route("GET", "/clip/v2", self.async_unknown_request)
            routes.add_manual_route("GET", "/eventstream/clip/v2", self.async_eventstream)
            routes.add_class_routes(self)
            # Add catch-all handler for unknown requests to api
            routes.add_manual_route("*", "/clip/v2/{tail:.*}", self.async_unknown_request)
        return routes

    async def async_stop(self):
        """Stop the v2 api."""
        pass

    async def async_eventstream(self, request):
        async with sse_response(request) as response:
            app = request.app
            queue = asyncio.Queue()
            print("Someone joined.")
            app["event_streams"].add(queue)
            await response.send(f": hi\n\n")
            try:
                while not response.task.done():
                    payload = await queue.get()
                    await response.send(payload)
                    queue.task_done()
            finally:
                app["channels"].remove(queue)
                print("Someone left.")

            #while counter > 0:  # ensure we stop at some point
            #    if len(HueObjects.eventstream) > 0:
            #        for index, messages in enumerate(HueObjects.eventstream):
            #            yield f"id: {int(time()) }:{index}\ndata: {json.dumps([messages], separators=(',', ':'))}\n\n"
            #        sleep(0.2)
            #    sleep(0.2)
            #    counter -= 1

        return response

    @routes.get("/clip/v2/resource")
    @authorizev2(check_user=True)
    async def async_get_all_resources(self, request: web.Request):
        data = [
            await self.__async_get_homekit(),
            await self.__async_get_matter(),
            await self.__async_get_bridge_home(),
        ]
        data.extend(await self.__async_get_grouped_light())
        data.extend(await self.__async_get_room())
        data.extend(await self.__async_get_device())
        data.extend(await self.__async_get_light())
        data.extend(await self.__async_get_zigbee_connectivity())
        data.extend(await self.__async_get_entertainment())
        # TODO sensors
        data.append(await self.__async_get_bridge())
        data.append(await self.__async_get_zigbee_discovery())
        # TODO entertainment_configuration
        # TODO behavior_scripts
        # TODO smart scene
        # TODO geofence client
        data.append(await self.__async_get_geolocation())
        return send_json_response_v2(data)

    @routes.get("/clip/v2/resource/homekit")
    @authorizev2(check_user=True)
    async def async_get_homekit(self, request: web.Request):
        return send_json_response_v2([await self.__async_get_homekit()])

    @routes.get("/clip/v2/resource/matter")
    @authorizev2(check_user=True)
    async def async_get_matter(self, request: web.Request):
        return send_json_response_v2([await self.__async_get_matter()])

    @routes.get("/clip/v2/resource/bridge_home")
    @authorizev2(check_user=True)
    async def async_get_bridge_home(self, request: web.Request):
        return send_json_response_v2([await self.__async_get_bridge_home()])

    @routes.get("/clip/v2/resource/grouped_light")
    @authorizev2(check_user=True)
    async def async_get_grouped_light(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_grouped_light())

    @routes.get("/clip/v2/resource/room")
    @authorizev2(check_user=True)
    async def async_get_room(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_room())

    @routes.get("/clip/v2/resource/device")
    @authorizev2(check_user=True)
    async def async_get_device(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_device())

    @routes.get("/clip/v2/resource/light")
    @authorizev2(check_user=True)
    async def async_get_light(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_light())

    @routes.put("/clip/v2/resource/light/{id}")
    @authorizev2(check_user=True)
    async def async_put_light(self, request: web.Request, request_data: dict):
        """Handle requests to perform action on a group of lights/room."""
        light_id = request.match_info["id"]
        entity_id = await self.ctl.config_instance.async_entity_id_from_light_id(
            light_id
        )
        await self.__async_light_action(entity_id, request_data)
        # Create success responses for all received keys
        return send_json_response_v2([])

    @routes.get("/clip/v2/resource/zigbee_connectivity")
    @authorizev2(check_user=True)
    async def async_get_zigbee_connectivity(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_zigbee_connectivity())

    @routes.get("/clip/v2/resource/entertainment")
    @authorizev2(check_user=True)
    async def async_get_entertainment(self, request: web.Request):
        return send_json_response_v2(await self.__async_get_entertainment())

    @routes.get("/clip/v2/resource/bridge")
    @authorizev2(check_user=True)
    async def async_get_bridge(self, request: web.Request):
        return send_json_response_v2([await self.__async_get_bridge()])

    @routes.get("/clip/v2/resource/geolocation")
    @authorizev2(check_user=True)
    async def async_get_geolocation(self, request: web.Request):
        return send_json_response_v2([await self.__async_get_geolocation()])

    async def __async_get_homekit(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["homekit"], bridge_id)),
            "status": "unpaired",
            "status_values": [
                "pairing",
                "paired",
                "unpaired"
            ],
            "type": "homekit"
        }
        return result

    async def __async_get_matter(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "has_qr_code": True,
            "id": str(uuid.uuid5(UUID_NAMESPACES["matter"], bridge_id)),
            "max_fabrics": 16,
            "type": "matter"
        }
        return result

    async def __async_get_bridge_home(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["bridge_home"], bridge_id)),
            "id_v1": "/groups/0",
            "children": [
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
                    "rtype": "device"
                }
            ],
            "services": [
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["grouped_light"], bridge_id)),
                    "rtype": "grouped_light"
                }
            ],
            "type": "bridge_home"
        }

        # TODO add sensors devices

        areas = await self.ctl.controller_hass.async_get_area_entities()
        for area in areas.values():
            result['children'].append({
                "rid": str(uuid.uuid5(UUID_NAMESPACES["room"], area.get('area_id'))),
                "rtype": "room"
            })

        return result

    async def __async_get_grouped_light(self) -> list:
        bridge_id = self.ctl.config_instance.bridge_id
        result = [{
            "id": str(uuid.uuid5(UUID_NAMESPACES["grouped_light"], bridge_id)),
            "id_v1": "/groups/0",
            "owner": {
                "rid": str(uuid.uuid5(UUID_NAMESPACES["bridge_home"], bridge_id)),
                "rtype": "bridge_home"
            },
            "on": { # TODO
                "on": True
            },
            "dimming": {
                "brightness": 100
            },
            "dimming_delta": {},
            "color_temperature": {},
            "color_temperature_delta": {},
            "color": {},
            "alert": {
                "action_values": [
                    "breathe"
                ]
            },
            "signaling": {
                "signal_values": [
                    "alternating",
                    "no_signal",
                    "on_off",
                    "on_off_color"
                ]
            },
            "dynamics": {},
            "type": "grouped_light"
        }]

        groups = await self.ctl.config_instance.async_get_storage_value(
            "groups", default={}
        )
        for group_id_v1, group_conf in groups.items():
            result.append({
                "id": str(uuid.uuid5(UUID_NAMESPACES["grouped_light"], group_conf['area_id'])),
                "id_v1": "/groups/" + group_id_v1,
                "owner": {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["room"], group_conf['area_id'])),
                    "rtype": "room"
                },
                "on": {
                    "on": group_conf['state']['any_on']
                },
                "dimming": {
                    "brightness": 0
                },
                "dimming_delta": {},
                "color_temperature": {},
                "color_temperature_delta": {},
                "color": {},
                "alert": {
                    "action_values": [
                        "breathe"
                    ]
                },
                "signaling": {
                    "signal_values": [
                        "no_signal",
                        "on_off"
                    ]
                },
                "dynamics": {},
                "type": "grouped_light"
            })

        return result

    async def __async_get_room(self) -> list:
        """Create a list of all rooms."""
        result = []

        areas = await self.ctl.controller_hass.async_get_area_entities()
        for area in areas.values():
            area_id = area.get('area_id')
            if area_id != "office": # TODO remove
                continue
            group_id_v1 = await self.ctl.config_instance.async_area_id_to_group_id_v1(area_id)
            new_room = {
                "id": str(uuid.uuid5(UUID_NAMESPACES["room"], area_id)),
                "id_v1": "/groups/" + group_id_v1,
                "children": [
                ],
                "services": [
                    {
                        "rid": str(uuid.uuid5(UUID_NAMESPACES["grouped_light"], area_id)),
                        "rtype": "grouped_light"
                    }
                ],
                "metadata": {
                    "name": area.get('name'),
                    "archetype": "bathroom"  # TODO
                },
                "type": "room"
            }

            for light in area.get('entities'):
                device = await async_get_device(self.ctl, light)
                new_room['children'].append({
                    "rid": device.hue_device_id,
                    "rtype": "device"
                })
            result.append(new_room)

        return result

    async def __async_get_device(self) -> list:
        """Create a list of all devices."""
        result = [
            await self.__async_bridge_to_device()
        ]
        for entity_id in self.ctl.controller_hass.get_entities():
            result.append(await self.__async_entity_to_device(entity_id))

        return result

    async def __async_get_light(self) -> list:
        """Create a list of all lights."""
        result = []
        for entity_id in self.ctl.controller_hass.get_entities():

            if not entity_id.startswith("light.signify_"): # TODO remove
                continue

            result.append(await self.__async_entity_to_light(entity_id))

        return result

    async def __async_light_action(self, entity_id: str, request_data: dict) -> None:
        """Translate the Hue api request data to actions on a light entity."""

        device = await async_get_device(self.ctl, entity_id)
        call = device.new_control_state()

        logging.info("set %s: %s", entity_id, request_data)

        if const.HUE_ATTR_ON in request_data:
            call.set_power_state(request_data[const.HUE_ATTR_ON][const.HUE_ATTR_ON])

        if color := request_data.get(const.HUE_ATTR_COLOR):
            if xy := color.get(const.HUE_ATTR_XY):
                call.set_xy(xy['x'], xy['y'])

        if const.HUE_ATTR_DIMMING in request_data and \
                (bri := request_data[const.HUE_ATTR_DIMMING].get(const.HUE_ATTR_BRIGHTNESS)):
            call.set_brightness(max(2, bri * 2.55))

        await call.async_execute()

    async def __async_get_zigbee_connectivity(self) -> list:
        """Create a list of all zigbee connectivities."""
        result = [
            await self.__async_bridge_to_zigbee_connectivity()
        ]
        for entity_id in self.ctl.controller_hass.get_entities():
            result.append(await self.__async_entity_to_zigbee_connectivity(entity_id))

        return result

    async def __async_get_entertainment(self) -> list:
        """Create a list of all entertainments."""
        result = [
            await self.__async_bridge_to_entertainment()
        ]
        for entity_id in self.ctl.controller_hass.get_entities():
            result.append(await self.__async_entity_to_entertainment(entity_id))

        return result

    async def __async_get_bridge(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        time_zone = self.ctl.config_instance.get_storage_value(
            "bridge_config", "timezone", tzlocal.get_localzone_name()
        )
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["bridge"], bridge_id)),
            "owner": {
                "rid": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
                "rtype": "device"
            },
            "bridge_id": bridge_id.lower(),
            "time_zone": {
                "time_zone": time_zone
            },
            "type": "bridge"
        }
        return result

    async def __async_get_zigbee_discovery(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["zigbee_device_discovery"], bridge_id)),
            "owner": {
                "rid": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
                "rtype": "device"
            },
            "status": "ready",
            "type": "zigbee_device_discovery"
        }
        return result

    async def __async_get_geolocation(self) -> dict:
        result = {
            "id": "cd986381-09f7-4292-ae89-290a666889a8",
            "type": "geolocation",
            "is_configured": False,
            "sun_today": {
                "sunset_time": "21:12:00",
                "day_type": "normal_day"
            }
        }
        return result

    async def __async_bridge_to_device(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
            "product_data": {
                "model_id": "BSB002",
                "manufacturer_name": "Signify Netherlands B.V.",
                "product_name": self.ctl.config_instance.bridge_name,
                "product_archetype": "bridge_v2",
                "certified": True,
                "software_version": "1.59.1959097030"
            },
            "metadata": {
                "name": self.ctl.config_instance.bridge_name,
                "archetype": "bridge_v2"
            },
            "identify": {},
            "services": [
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["bridge"], bridge_id)),
                    "rtype": "bridge"
                },
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["zigbee_connectivity"], bridge_id)),
                    "rtype": "zigbee_connectivity"
                },
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["entertainment"], bridge_id)),
                    "rtype": "entertainment"
                },
                {
                    "rid": str(uuid.uuid5(UUID_NAMESPACES["zigbee_device_discovery"], bridge_id)),
                    "rtype": "zigbee_device_discovery"
                }
            ],
            "type": "device"
        }
        return result

    async def __async_bridge_to_zigbee_connectivity(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["zigbee_connectivity"], bridge_id)),
            "owner": {
                "rid": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
                "rtype": "device"
            },
            "status": "connected",
            "mac_address": self.ctl.config_instance.mac_addr,
            "channel": {
                "status": "set",
                "value": "channel_15"
            },
            "type": "zigbee_connectivity"
        }
        return result

    async def __async_bridge_to_entertainment(self) -> dict:
        bridge_id = self.ctl.config_instance.bridge_id
        result = {
            "id": str(uuid.uuid5(UUID_NAMESPACES["entertainment"], bridge_id)),
            "owner": {
                "rid": str(uuid.uuid5(UUID_NAMESPACES["device"], bridge_id)),
                "rtype": "device"
            },
            "renderer": False,
            "proxy": True,
            "equalizer": False,
            "max_streams": 1,
            "type": "entertainment"
        }
        return result

    async def __async_entity_to_device(self, entity_id: str) -> dict:
        """Convert an entity to its Hue device JSON representation."""
        device = await async_get_device(self.ctl, entity_id)

        retval = {
            "id": device.hue_id("device"),
            "id_v1": "/lights/" + device.light_id_v1,
            "product_data": {
                "model_id": device.device_properties.model,
                "manufacturer_name": device.device_properties.manufacturer,
                "product_name": device.device_properties.model,  # TODO map
                "product_archetype": "hue_go",  # TODO
                "certified": True,
                "software_version": device.device_properties.sw_version, # TODO format
                "hardware_platform_type": "100b-108"  # TODO
            },
            "metadata": {
                "name": device.name,
                "archetype": "hue_go"  # TODO
            },
            "identify": {},
            "services": [
                {
                    "rid": device.hue_light_id,
                    "rtype": "light"
                },
                {
                    "rid": device.hue_zigbee_connectivity_id,
                    "rtype": "zigbee_connectivity"
                },
                {
                    "rid": device.hue_entertainment_id,
                    "rtype": "entertainment"
                }
            ],
            "type": "device"
        }
        return retval

    async def __async_entity_to_light(self, entity_id: str) -> dict:
        """Convert an entity to its Hue Light JSON representation."""
        device = await async_get_device(self.ctl, entity_id)

        retval = {
            "id": device.hue_light_id,
            "id_v1": "/lights/" + device.light_id_v1,
            "owner": {
                "rid": device.hue_device_id,
                "rtype": "device"
            },
            "metadata": {
                "name": device.name,
                "archetype": "pendant_round"  # TODO
            },
            "identify": {},
            "dynamics": {  ## TODO
                "status": "none",
                "status_values": [
                    "none",
                    "dynamic_palette"
                ],
                "speed": 0,
                "speed_valid": False
            },
            "alert": {  # TODO
                "action_values": [
                    "breathe"
                ]
            },
            "signaling": { ## TODO
                "signal_values": [
                    "no_signal",
                    "on_off",
                    "on_off_color",
                    "alternating"
                ]
            },
            "mode": "normal",  # TODO
            "effects": {  # TODO
                "status_values": [
                    "no_effect",
                    "candle"
                ],
                "status": "no_effect",
                "effect_values": [
                    "no_effect",
                    "candle",
                    "fire",
                    "prism"
                ]
            },
            "powerup": {  # TODO
                "preset": "safety",
                "configured": True,
                "on": {
                    "mode": "on",
                    "on": {
                        "on": True
                    }
                },
                "dimming": {
                    "mode": "dimming",
                    "dimming": {
                        "brightness": 100
                    }
                },
                "color": {
                    "mode": "color_temperature",
                    "color_temperature": {
                        "mirek": 366
                    }
                }
            },
            "type": "light"
        }
        if isinstance(device, controllers.devices.OnOffDevice):
            retval.update({
                "on": {
                    "on": device.power_state
                },
            })
        if isinstance(device, controllers.devices.BrightnessDevice):
            retval.update({
                "dimming": {
                    "brightness": round(10000 * device.brightness / 255) / 100,
                    "min_dim_level": 2  # TODO
                },
                "dimming_delta": {}
            })
        if isinstance(device, controllers.devices.RGBDevice):
            gamut_color = device.gamut_color
            retval.update({
                "color": {
                    "xy": {
                        "x": round(device.xy_color[0], 4),
                        "y": round(device.xy_color[1], 4)
                    },
                    "gamut": {
                        "red": {
                            "x": round(gamut_color[0][0], 4),
                            "y": round(gamut_color[0][1], 4)
                        },
                        "green": {
                            "x": round(gamut_color[1][0], 4),
                            "y": round(gamut_color[1][1], 4)
                        },
                        "blue": {
                            "x": round(gamut_color[2][0], 4),
                            "y": round(gamut_color[2][1], 4)
                        }
                    },
                    "gamut_type": "C"  # TODO
                }
            })
        if isinstance(device, controllers.devices.RGBWWDevice):
            retval.update({
                "color_temperature": {
                    "mirek": device.color_temp,
                    "mirek_valid": True,  # TODO
                    "mirek_schema": {
                        "mirek_minimum": device.min_mireds,
                        "mirek_maximum": device.max_mireds
                    }
                },
                "color_temperature_delta": {},
            })
        return retval

    async def __async_entity_to_zigbee_connectivity(self, entity_id: str) -> dict:
        """Convert an entity to its Hue Zigbee Connectivity JSON representation."""
        device = await async_get_device(self.ctl, entity_id)
        status = "connected" if device.reachable else "connectivity_issue"

        retval = {
            "id": device.hue_zigbee_connectivity_id,
            "id_v1": "/lights/" + device.light_id_v1,
            "owner": {
                "rid": device.hue_device_id,
                "rtype": "device"
            },
            "status": status,
            "mac_address": device.device_properties.mac_address, # TODO handle missing
            "type": "zigbee_connectivity"
        }
        return retval

    async def __async_entity_to_entertainment(self, entity_id: str) -> dict:
        """Convert an entity to its Hue Entertainment JSON representation."""
        device = await async_get_device(self.ctl, entity_id)

        retval = {
            "id": device.hue_entertainment_id,
            "id_v1": "/lights/" + device.light_id_v1,
            "owner": {
                "rid": device.hue_device_id,
                "rtype": "device"
            },
            "renderer": True,
            "renderer_reference": {
                "rid": device.hue_light_id,
                "rtype": "light"
            },
            "proxy": True,
            "equalizer": True,
            "segments": {
                "configurable": False,
                "max_segments": 1,
                "segments": [
                    {
                        "start": 0,
                        "length": 1
                    }
                ]
            },
            "type": "entertainment"
        }
        return retval
