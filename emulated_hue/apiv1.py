"""Support for a Hue API to control Home Assistant."""
import contextlib
import copy
import datetime
import functools
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, cast

import tzlocal
from aiohttp import web

from emulated_hue import const, controllers
from emulated_hue.controllers import Controller
from emulated_hue.controllers.devices import async_get_device
from emulated_hue.utils import (
    ClassRouteTableDef,
    convert_color_mode,
    convert_flash_state,
    send_error_response,
    send_json_response,
    send_success_response,
    update_dict,
    wrap_number,
)

if TYPE_CHECKING:
    from emulated_hue import HueEmulator
else:
    HueEmulator = "HueEmulator"

LOGGER = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_static")
DESCRIPTION_FILE = os.path.join(STATIC_DIR, "description.xml")


def check_request(check_user=True, log_request=True):
    """Run some common logic to log and validate all requests (used as a decorator)."""

    def func_wrapper(func):
        @functools.wraps(func)
        async def wrapped_func(cls: "HueApiV1Endpoints", request: web.Request):
            if log_request:
                LOGGER.debug("[%s] %s %s", request.remote, request.method, request.path)
            # check username
            if check_user:
                username = request.match_info.get("username")
                if not username or not await cls.ctl.config_instance.async_get_user(
                    username
                ):
                    path = request.path.replace(username, "")
                    LOGGER.debug("[%s] Invalid username (api key)", request.remote)
                    return send_error_response(path, "unauthorized user", 1)
            # check and unpack (json) body if needed
            if request.method in ["PUT", "POST"]:
                request_text = await request.text()
                try:
                    request_data = await request.text()
                    # clean request_data for weird apps like f.lux
                    request_data = request_data.rstrip("\x00")
                    request_data = json.loads(request_data)
                except ValueError:
                    LOGGER.warning(
                        "Invalid json in request: %s --> %s", request, request_text
                    )
                    return send_error_response("", "body contains invalid json", 2)
                LOGGER.debug(request_text)
                return await func(cls, request, request_data)
            return await func(cls, request)

        return wrapped_func

    return func_wrapper


# pylint: disable=invalid-name
routes = ClassRouteTableDef()
# pylint: enable=invalid-name


class HueApiV1Endpoints:
    """Hue API v1 endpoints."""

    def __init__(self, ctl: Controller):
        """Initialize the v1 api."""
        self.ctl = ctl
        self._new_lights = {}
        self._timestamps = {}
        self._prev_data = {}
        with open(DESCRIPTION_FILE, encoding="utf-8") as fdesc:
            self._description_xml = fdesc.read()

    @property
    def route(self):
        """Return routes for external access."""
        if not len(routes):
            routes.add_manual_route("GET", "/api", self.async_unknown_request)
            # add class routes
            routes.add_class_routes(self)
            # Add catch-all handler for unknown requests to api
            routes.add_manual_route("*", "/api/{tail:.*}", self.async_unknown_request)
        return routes

    async def async_stop(self):
        """Stop the v1 api."""
        pass

    @routes.post("/api")
    @check_request(False)
    async def async_post_auth(self, request: web.Request, request_data: dict):
        """Handle requests to create a username for the emulated hue bridge."""
        if "devicetype" not in request_data:
            LOGGER.warning("devicetype not specified")
            # custom error message
            return send_error_response(request.path, "devicetype not specified", 302)
        if request_data["devicetype"].startswith("home-assistant"):
            LOGGER.error("Pairing with Home Assistant is explicitly disabled.")
            return send_error_response(
                request.path, "Pairing with Home Assistant is explicitly disabled", 901
            )
        if not self.ctl.config_instance.link_mode_enabled:
            await self.ctl.config_instance.async_enable_link_mode_discovery()
            return send_error_response(request.path, "link button not pressed", 101)

        userdetails = await self.ctl.config_instance.async_create_user(
            request_data["devicetype"]
        )
        response = [{"success": {"username": userdetails["username"]}}]
        if request_data.get("generateclientkey"):
            response[0]["success"]["clientkey"] = userdetails["clientkey"]
        LOGGER.info("Client %s registered", userdetails["name"])
        await self.ctl.config_instance.async_disable_link_mode()
        self.ctl.loop.create_task(
            self.ctl.config_instance.async_disable_link_mode_discovery()
        )
        return send_json_response(response)

    @routes.get("/api/{username}/lights")
    @check_request()
    async def async_get_lights(self, request: web.Request):
        """Handle requests to retrieve the info all lights."""
        return send_json_response(await self.__async_get_all_lights())

    @routes.get("/api/{username}/lights/new")
    @check_request()
    async def async_get_new_lights(self, request: web.Request):
        """Handle requests to retrieve new added lights to the (virtual) bridge."""
        return send_json_response(self._new_lights)

    @routes.post("/api/{username}/lights")
    @check_request()
    async def async_search_new_lights(self, request: web.Request, request_data):
        """Handle requests to retrieve new added lights to the (virtual) bridge."""
        username = request.match_info["username"]
        LOGGER.info(
            "Search mode activated. Any deleted/disabled lights will be reactivated."
        )

        def auto_disable():
            self._new_lights = {}

        self.ctl.loop.call_later(60, auto_disable)

        # enable all disabled lights and groups
        for entity_id in self.ctl.controller_hass.get_entities():
            light_id = await self.ctl.config_instance.async_entity_id_to_light_id(
                entity_id
            )
            light_config = await self.ctl.config_instance.async_get_light_config(
                light_id
            )
            if not light_config["enabled"]:
                light_config["enabled"] = True
                await self.ctl.config_instance.async_set_storage_value(
                    "lights", light_id, light_config
                )
                # add to new_lights for the app to show a special badge
                self._new_lights[light_id] = await self.__async_entity_to_hue(entity_id)
        groups = await self.ctl.config_instance.async_get_storage_value(
            "groups", default={}
        )
        for group_id, group_conf in groups.items():
            if "enabled" in group_conf and not group_conf["enabled"]:
                group_conf["enabled"] = True
                await self.ctl.config_instance.async_set_storage_value(
                    "groups", group_id, group_conf
                )
        return send_success_response(request.path, {}, username)

    @routes.get("/api/{username}/lights/{light_id}")
    @check_request()
    async def async_get_light(self, request: web.Request):
        """Handle requests to retrieve the info for a single light."""
        light_id = request.match_info["light_id"]
        if light_id == "new":
            return await self.async_get_new_lights(request)
        entity_id = await self.ctl.config_instance.async_entity_id_from_light_id(
            light_id
        )
        result = await self.__async_entity_to_hue(entity_id)
        return send_json_response(result)

    @routes.put("/api/{username}/lights/{light_id}/state")
    @check_request()
    async def async_put_light_state(self, request: web.Request, request_data: dict):
        """Handle requests to perform action on a group of lights/room."""
        light_id = request.match_info["light_id"]
        username = request.match_info["username"]
        entity_id = await self.ctl.config_instance.async_entity_id_from_light_id(
            light_id
        )
        await self.__async_light_action(entity_id, request_data)
        # Create success responses for all received keys
        return send_success_response(request.path, request_data, username)

    @routes.get("/api/{username}/groups")
    @check_request()
    async def async_get_groups(self, request: web.Request):
        """Handle requests to retrieve all rooms/groups."""
        groups = await self.__async_get_all_groups()
        return send_json_response(groups)

    @routes.get("/api/{username}/groups/{group_id}")
    @check_request()
    async def async_get_group(self, request: web.Request):
        """Handle requests to retrieve info for a single group."""
        group_id: str = request.match_info["group_id"]
        result: dict | None = None
        if group_id.isdigit():
            groups = await self.__async_get_all_groups()
            result = groups.get(group_id)
        # else:
        # TODO: Return group 0 if group_id is not found
        if result:
            return send_json_response(result)
        else:
            return send_error_response(
                request.path, "resource, {path}, not available", 3
            )

    @routes.put("/api/{username}/groups/{group_id}/action")
    @check_request()
    async def async_group_action(self, request: web.Request, request_data: dict):
        """Handle requests to perform action on a group of lights/room."""
        group_id = request.match_info["group_id"]
        username = request.match_info["username"]
        # instead of directly getting groups should have a property
        # get groups instead so we can easily modify it
        group_conf = await self.ctl.config_instance.async_get_storage_value(
            "groups", group_id
        )
        if group_id == "0" and "scene" in request_data:
            # scene request
            scene = await self.ctl.config_instance.async_get_storage_value(
                "scenes", request_data["scene"], default={}
            )
            for light_id, light_state in scene["lightstates"].items():
                entity_id = (
                    await self.ctl.config_instance.async_entity_id_from_light_id(
                        light_id
                    )
                )
                await self.__async_light_action(entity_id, light_state)
        else:
            # forward request to all group lights
            # may need refactor to make __async_get_group_lights not an
            # async generator to instead return a dict
            async for entity_id in self.__async_get_group_lights(group_id):
                await self.__async_light_action(entity_id, request_data)
        if group_conf and "stream" in group_conf:
            # Request streaming stop
            # Duplicate code here. Method instead?
            LOGGER.info(
                "Stop Entertainment mode for group %s - params: %s",
                group_id,
                request_data,
            )
            self.ctl.config_instance.stop_entertainment()
        # Create success responses for all received keys
        return send_success_response(request.path, request_data, username)

    @routes.post("/api/{username}/groups")
    @check_request()
    async def async_create_group(self, request: web.Request, request_data: dict):
        """Handle requests to create a new group."""
        if "class" not in request_data:
            request_data["class"] = "Other"
        if "name" not in request_data:
            request_data["name"] = ""
        item_id = await self.__async_create_local_item(request_data, "groups")
        return send_json_response([{"success": {"id": item_id}}])

    @routes.put("/api/{username}/groups/{group_id}")
    @check_request()
    async def async_update_group(self, request: web.Request, request_data: dict):
        """Handle requests to update a group."""
        group_id = request.match_info["group_id"]
        username = request.match_info["username"]
        group_conf = await self.ctl.config_instance.async_get_storage_value(
            "groups", group_id
        )
        if not group_conf:
            return send_error_response(request.path, "no group config", 404)
        update_dict(group_conf, request_data)

        # Hue entertainment support (experimental)
        if "stream" in group_conf:
            if group_conf["stream"].get("active"):
                # Requested streaming start
                LOGGER.debug(
                    "Start Entertainment mode for group %s - params: %s",
                    group_id,
                    request_data,
                )
                del group_conf["stream"]["active"]
                user_data = await self.ctl.config_instance.async_get_user(username)
                self.ctl.config_instance.start_entertainment(group_conf, user_data)

                group_conf["stream"]["owner"] = username
                if not group_conf["stream"].get("proxymode"):
                    group_conf["stream"]["proxymode"] = "auto"
                if not group_conf["stream"].get("proxynode"):
                    group_conf["stream"]["proxynode"] = "/bridge"
            else:
                # Request streaming stop
                LOGGER.info(
                    "Stop Entertainment mode for group %s - params: %s",
                    group_id,
                    request_data,
                )
                self.ctl.config_instance.stop_entertainment()

        await self.ctl.config_instance.async_set_storage_value(
            "groups", group_id, group_conf
        )
        return send_success_response(request.path, request_data, username)

    @routes.put("/api/{username}/lights/{light_id}")
    @check_request()
    async def async_update_light(self, request: web.Request, request_data: dict):
        """Handle requests to update a light."""
        light_id = request.match_info["light_id"]
        username = request.match_info["username"]
        light_conf = await self.ctl.config_instance.async_get_storage_value(
            "lights", light_id
        )
        if not light_conf:
            return send_error_response(request.path, "no light config", 404)
        if "name" in request_data:
            light_conf = await self.ctl.config_instance.async_get_light_config(light_id)
            entity_id = light_conf["entity_id"]
            device = await async_get_device(self.ctl, entity_id)
            device.name = request_data["name"]
        return send_success_response(request.path, request_data, username)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}")
    @check_request()
    async def async_get_localitems(self, request: web.Request):
        """Handle requests to retrieve localitems (e.g. scenes)."""
        itemtype = request.match_info["itemtype"]
        result = await self.ctl.config_instance.async_get_storage_value(
            itemtype, default={}
        )
        return send_json_response(result)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}/{item_id}")
    @check_request()
    async def async_get_localitem(self, request: web.Request):
        """Handle requests to retrieve info for a single localitem."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        items = await self.ctl.config_instance.async_get_storage_value(itemtype)
        result = items.get(item_id, {})
        return send_json_response(result)

    @routes.post("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}")
    @check_request()
    async def async_create_localitem(self, request: web.Request, request_data: dict):
        """Handle requests to create a new localitem."""
        itemtype = request.match_info["itemtype"]
        item_id = await self.__async_create_local_item(request_data, itemtype)
        return send_json_response([{"success": {"id": item_id}}])

    @routes.put("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}/{item_id}")
    @check_request()
    async def async_update_localitem(self, request: web.Request, request_data: dict):
        """Handle requests to update an item in localstorage."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        username = request.match_info["username"]
        local_item = await self.ctl.config_instance.async_get_storage_value(
            itemtype, item_id
        )
        if not local_item:
            return send_error_response(request.path, "no localitem", 404)
        update_dict(local_item, request_data)
        await self.ctl.config_instance.async_set_storage_value(
            itemtype, item_id, local_item
        )
        return send_success_response(request.path, request_data, username)

    @routes.delete(
        "/api/{username}/{itemtype:(?:scenes|rules|resourcelinks|groups|lights)}/{item_id}"
    )
    @check_request()
    async def async_delete_localitem(self, request: web.Request):
        """Handle requests to delete a item from localstorage."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        await self.ctl.config_instance.async_delete_storage_value(itemtype, item_id)
        result = [{"success": f"/{itemtype}/{item_id} deleted."}]
        return send_json_response(result)

    @routes.get("/api/{username:[^/]+/{0,1}|}config{tail:.*}")
    @check_request(check_user=False)
    async def async_get_bridge_config(self, request: web.Request):
        """Process a request to get (full or partial) config of this emulated bridge."""
        username = request.match_info.get("username")
        valid_user = True
        if not username or not await self.ctl.config_instance.async_get_user(username):
            valid_user = False
        result = await self.__async_get_bridge_config(full_details=valid_user)
        return send_json_response(result)

    @routes.put("/api/{username}/config")
    @check_request()
    async def async_change_config(self, request: web.Request, request_data: dict):
        """Process a request to change a config value."""
        username = request.match_info["username"]
        # just log this request and return succes
        LOGGER.debug("Change config called with params: %s", request_data)
        for key, value in request_data.items():
            if key == "linkbutton" and value:
                # prevent storing value in config
                if not self.ctl.config_instance.link_mode_enabled:
                    await self.ctl.config_instance.async_enable_link_mode()
            else:
                await self.ctl.config_instance.async_set_storage_value(
                    "bridge_config", key, value
                )
        return send_success_response(request.path, request_data, username)

    async def async_scene_to_full_state(self) -> dict:
        """Return scene data, removing lightstates and adds group lights instead."""
        scenes = await self.ctl.config_instance.async_get_storage_value(
            "scenes", default={}
        )
        scenes = copy.deepcopy(scenes)
        for _scene_num, scene_data in scenes.items():
            scenes_group = scene_data["group"]
            # Remove lightstates only if existing
            scene_data.pop("lightstates", None)
            scene_data["lights"] = await self.__async_get_group_id(scenes_group)
        return scenes

    @routes.get("/api/{username}")
    @check_request()
    async def get_full_state(self, request: web.Request):
        """Return full state view of emulated hue."""
        json_response = {
            "config": await self.__async_get_bridge_config(True),
            "schedules": await self.ctl.config_instance.async_get_storage_value(
                "schedules", default={}
            ),
            "rules": await self.ctl.config_instance.async_get_storage_value(
                "rules", default={}
            ),
            "scenes": await self.async_scene_to_full_state(),
            "resourcelinks": await self.ctl.config_instance.async_get_storage_value(
                "resourcelinks", default={}
            ),
            "lights": await self.__async_get_all_lights(),
            "groups": await self.__async_get_all_groups(),
            "sensors": {
                "1": {
                    "state": {"daylight": None, "lastupdated": "none"},
                    "config": {
                        "on": True,
                        "configured": False,
                        "sunriseoffset": 30,
                        "sunsetoffset": -30,
                    },
                    "name": "Daylight",
                    "type": "Daylight",
                    "modelid": "PHDL00",
                    "manufacturername": "Signify Netherlands B.V.",
                    "swversion": "1.0",
                }
            },
        }

        return send_json_response(json_response)

    @routes.get("/api/{username}/sensors")
    @check_request()
    async def async_get_sensors(self, request: web.Request):
        """Return sensors on the (virtual) bridge."""
        # not supported yet but prevent errors
        return send_json_response({})

    @routes.get("/api/{username}/sensors/new")
    @check_request()
    async def async_get_new_sensors(self, request: web.Request):
        """Return all new discovered sensors on the (virtual) bridge."""
        # not supported yet but prevent errors
        return send_json_response({})

    @routes.get("/description.xml")
    @check_request(False)
    async def async_get_description(self, request: web.Request):
        """Serve the service description file."""
        resp_text = self._description_xml.format(
            self.ctl.config_instance.ip_addr,
            self.ctl.config_instance.http_port,
            f"{self.ctl.config_instance.bridge_name} ({self.ctl.config_instance.ip_addr})",
            self.ctl.config_instance.bridge_serial,
            self.ctl.config_instance.bridge_uid,
        )
        return web.Response(text=resp_text, content_type="text/xml")

    @routes.get("/link/{token}")
    @check_request(False)
    async def async_link(self, request: web.Request):
        """Enable link mode on the bridge."""
        token = request.match_info["token"]
        # token needs to match the discovery token
        if (
            not token
            or not self.ctl.config_instance.link_mode_discovery_key
            or token != self.ctl.config_instance.link_mode_discovery_key
        ):
            return web.Response(body="Invalid token supplied!", status=302)
        html_template = """
            <html>
                <body>
                    <h2>Link mode is enabled for 5 minutes.</h2>
                </body>
                <script>
                  setTimeout(function() {
                      window.close()
                  }, 2000);
                </script>
            </html>"""
        await self.ctl.config_instance.async_enable_link_mode()
        await self.ctl.config_instance.async_disable_link_mode_discovery()
        return web.Response(text=html_template, content_type="text/html")

    @routes.get("/api/{username}/capabilities")
    @check_request()
    async def async_get_capabilities(self, request: web.Request):
        """Return an overview of the capabilities."""
        json_response = {
            "lights": {"available": 50},
            "sensors": {
                "available": 60,
                "clip": {"available": 60},
                "zll": {"available": 60},
                "zgp": {"available": 60},
            },
            "groups": {"available": 60},
            "scenes": {"available": 100, "lightstates": {"available": 1500}},
            "rules": {"available": 100, "lightstates": {"available": 1500}},
            "schedules": {"available": 100},
            "resourcelinks": {"available": 100},
            "whitelists": {"available": 100},
            "timezones": {"value": self.ctl.config_instance.definitions["timezones"]},
            "streaming": {"available": 1, "total": 10, "channels": 10},
        }

        return send_json_response(json_response)

    @routes.get("/api/{username}/info/timezones")
    @check_request()
    async def async_get_timezones(self, request: web.Request):
        """Return all timezones."""
        return send_json_response(self.ctl.config_instance.definitions["timezones"])

    async def async_unknown_request(self, request: web.Request):
        """Handle unknown requests (catch-all)."""
        request_data = await request.text()
        if request_data:
            LOGGER.warning("Invalid/unknown request: %s --> %s", request, request_data)
        else:
            LOGGER.warning("Invalid/unknown request: %s", request)
        if request.method == "GET":
            address = request.path.lstrip("/").split("/")
            # Ensure a resource is requested
            if len(address) > 2:
                username = address[1]
                if not await self.ctl.config_instance.async_get_user(username):
                    return send_error_response(request.path, "unauthorized user", 1)
            return send_error_response(
                request.path, "method, GET, not available for resource, {path}", 4
            )
        return send_error_response(request.path, "unknown request", 404)

    async def __async_light_action(self, entity_id: str, request_data: dict) -> None:
        """Translate the Hue api request data to actions on a light entity."""

        device = await async_get_device(self.ctl, entity_id)

        call = device.new_control_state()
        if transition := request_data.get(const.HUE_ATTR_TRANSITION):
            # Duration of the transition from the light to the new state
            # is given as a multiple of 100ms and defaults to 4 (400ms).
            call.set_transition_ms(transition * 100)
        else:
            call.set_transition_ms(400)

        if const.HUE_ATTR_ON in request_data and not request_data[const.HUE_ATTR_ON]:
            call.set_power_state(False)
        else:
            call.set_power_state(True)

            # Don't error if we attempt to set an attribute that doesn't exist
            if bri := request_data.get(const.HUE_ATTR_BRI):
                with contextlib.suppress(AttributeError):
                    call.set_brightness(bri)

            sat = request_data.get(const.HUE_ATTR_SAT)
            hue = request_data.get(const.HUE_ATTR_HUE)
            if sat and hue:
                hue = wrap_number(hue, 0, const.HUE_ATTR_HUE_MAX)
                sat = wrap_number(sat, 0, const.HUE_ATTR_SAT_MAX)
                # Convert hs values to hass hs values
                hue = int((hue / const.HUE_ATTR_HUE_MAX) * 360)
                sat = int((sat / const.HUE_ATTR_SAT_MAX) * 100)
                with contextlib.suppress(AttributeError):
                    call.set_hue_sat(hue, sat)

            if color_temp := request_data.get(const.HUE_ATTR_CT):
                call.set_color_temperature(color_temp)

            if (
                (xy := request_data.get(const.HUE_ATTR_XY))
                and type(xy) is list
                and len(xy) == 2
            ):
                with contextlib.suppress(AttributeError):
                    call.set_xy(xy[0], xy[1])

            # effects probably don't work
            if effect := request_data.get(const.HUE_ATTR_EFFECT):
                with contextlib.suppress(AttributeError):
                    call.set_effect(effect)
            if alert := request_data.get(const.HUE_ATTR_ALERT):
                if alert == "select":
                    with contextlib.suppress(AttributeError):
                        call.set_flash("short")
                elif alert == "lselect":
                    with contextlib.suppress(AttributeError):
                        call.set_flash("long")

        await call.async_execute()

    async def __async_entity_to_hue(
        self,
        entity_id: str,
    ) -> dict:
        """Convert an entity to its Hue bridge JSON representation."""
        device = await async_get_device(self.ctl, entity_id)

        retval = {
            "state": {
                "on": device.power_state,
                "reachable": device.reachable,
                "mode": "homeautomation",
            },
            "name": device.name,
            "uniqueid": device.unique_id,
            "swupdate": {
                "state": "noupdates",
                "lastinstall": datetime.datetime.now().isoformat().split(".")[0],
            },
            "config": {
                "config": {
                    "archetype": "sultanbulb",
                    "direction": "omnidirectional",
                    "function": "mixed",
                    "startup": {"configured": True, "mode": "safety"},
                }
            },
        }
        current_state = {}

        def get_device_attrs():
            nonlocal device
            device_type = type(device)
            if device_type == controllers.devices.OnOffDevice:
                # On/off light (Zigbee Device ID: 0x0000)
                # Supports groups, scenes, on/off control
                retval.update(
                    self.ctl.config_instance.definitions["lights"]["On/off light"]
                )
                return
            if isinstance(device, controllers.devices.BrightnessDevice):
                device = cast(controllers.devices.BrightnessDevice, device)
                current_state[const.HUE_ATTR_BRI] = device.brightness
                current_state[const.HUE_ATTR_ALERT] = (
                    convert_flash_state(device.flash_state, const.HASS)
                    if device.flash_state
                    else "none"
                )
            if device_type == controllers.devices.BrightnessDevice:
                # Dimmable light (Zigbee Device ID: 0x0100)
                # Supports groups, scenes, on/off and dimming
                retval["type"] = "Dimmable light"
                retval.update(
                    self.ctl.config_instance.definitions["lights"]["Dimmable light"]
                )
                return
            if isinstance(device, controllers.devices.CTDevice):
                device = cast(controllers.devices.CTDevice, device)
                capabilities = {
                    "capabilities": {
                        "control": {
                            "ct": {
                                "min": device.min_mireds or 153,
                                "max": device.max_mireds or 500,
                            }
                        }
                    }
                }
                retval.update(capabilities)
                current_state[const.HUE_ATTR_CT] = device.color_temp
            if device_type == controllers.devices.CTDevice:
                # Color temperature light (Zigbee Device ID: 0x0220)
                # Supports groups, scenes, on/off, dimming, and setting of a color temperature
                retval.update(
                    self.ctl.config_instance.definitions["lights"][
                        "Color temperature light"
                    ]
                )
                return
            if isinstance(device, controllers.devices.RGBDevice):
                device = cast(controllers.devices.RGBDevice, device)
                current_state[const.HUE_ATTR_EFFECT] = device.effect or "none"
                current_state[const.HUE_ATTR_XY] = device.xy_color
                # Convert hass hs values to hue hs values
                current_state[const.HUE_ATTR_HUE] = int(
                    device.hue_sat[0] / 360 * const.HUE_ATTR_HUE_MAX
                )
                current_state[const.HUE_ATTR_SAT] = int(
                    device.hue_sat[1] / 100 * const.HUE_ATTR_SAT_MAX
                )
            if device_type == controllers.devices.RGBDevice:
                # Color light (Zigbee Device ID: 0x0200)
                # Supports on/off, dimming and color control (hue/saturation, enhanced hue, color loop and XY)
                retval.update(
                    self.ctl.config_instance.definitions["lights"]["Color light"]
                )
                return

            current_state[const.HUE_ATTR_COLORMODE] = convert_color_mode(
                device.color_mode, const.HASS
            )
            # Extended Color light (Zigbee Device ID: 0x0210)
            # Same as Color light, but which supports additional setting of color temperature
            retval.update(
                self.ctl.config_instance.definitions["lights"]["Extended color light"]
            )
            return

        get_device_attrs()
        retval["state"].update(current_state)

        # attempt to update from hass device attributes
        retval["manufacturername"] = (
            device.device_properties.manufacturer or retval["manufacturername"]
        )
        retval["modelid"] = device.device_properties.model or retval["modelid"]
        retval["productname"] = device.device_properties.name or retval["productname"]
        retval["swversion"] = device.device_properties.sw_version or retval["swversion"]

        return retval

    async def __async_get_all_lights(self) -> dict:
        """Create a dict of all lights."""
        result = {}
        for entity_id in self.ctl.controller_hass.get_entities():
            device = await async_get_device(self.ctl, entity_id)
            if not device.enabled:
                continue
            result[device.light_id] = await self.__async_entity_to_hue(entity_id)
        return result

    async def __async_create_local_item(
        self, data: Any, itemtype: str = "scenes"
    ) -> str:
        """Create item in storage of given type (scenes etc.)."""
        local_items = await self.ctl.config_instance.async_get_storage_value(
            itemtype, default={}
        )
        # get first available id
        for i in range(1, 1000):
            item_id = str(i)
            if item_id not in local_items:
                break
        if (
            itemtype == "groups"
            and data["type"] in ["LightGroup", "Room", "Zone"]
            and "class" not in data
        ):
            data["class"] = "Other"
        await self.ctl.config_instance.async_set_storage_value(itemtype, item_id, data)
        return item_id

    async def __async_get_all_groups(self) -> dict:
        """Create a dict of all groups."""
        result = {}

        # local groups first
        groups = await self.ctl.config_instance.async_get_storage_value(
            "groups", default={}
        )
        for group_id, group_conf in groups.items():
            # no area_id = not hass area
            if "area_id" not in group_conf:
                if "stream" in group_conf:
                    group_conf = copy.deepcopy(group_conf)
                    if self.ctl.config_instance.entertainment_active:
                        group_conf["stream"]["active"] = True
                    else:
                        group_conf["stream"]["active"] = False
                result[group_id] = group_conf

        # Hass areas/rooms
        areas = await self.ctl.controller_hass.async_get_area_entities()
        for area in areas.values():
            area_id = area["area_id"]
            group_id = await self.ctl.config_instance.async_area_id_to_group_id(area_id)
            group_conf = await self.ctl.config_instance.async_get_group_config(group_id)
            if not group_conf["enabled"]:
                continue
            result[group_id] = group_conf.copy()
            result[group_id]["lights"] = []
            result[group_id]["name"] = group_conf["name"] or area["name"]
            lights_on = 0
            # get all entities for this device
            for entity_id in area["entities"]:
                light_id = await self.ctl.config_instance.async_entity_id_to_light_id(
                    entity_id
                )
                result[group_id]["lights"].append(light_id)
                device = await async_get_device(self.ctl, entity_id)
                if device.power_state:
                    lights_on += 1
                    if lights_on == 1:
                        # set state of first light as group state
                        entity_obj = await self.__async_entity_to_hue(entity_id)
                        result[group_id]["action"] = entity_obj["state"]
            result[group_id]["state"]["any_on"] = lights_on > 0
            result[group_id]["state"]["all_on"] = lights_on == len(
                result[group_id]["lights"]
            )
            # do not return empty areas/rooms
            if len(result[group_id]["lights"]) == 0:
                result.pop(group_id, None)

        return result

    async def __async_get_group_id(self, group_id: str) -> dict:
        """Get group data for a group."""
        if group_id == "0":
            all_lights = await self.__async_get_all_lights()
            group_conf = {"lights": []}
            for light_id in all_lights:
                group_conf["lights"].append(light_id)
        else:
            group_conf = await self.ctl.config_instance.async_get_storage_value(
                "groups", group_id
            )
        if not group_conf:
            raise RuntimeError("Invalid group id: %s" % group_id)
        return group_conf

    async def __async_get_group_lights(
        self, group_id: str
    ) -> AsyncGenerator[str, None]:
        """Get all light entities for a group."""
        group_conf = await self.__async_get_group_id(group_id)

        # Hass group (area)
        if group_area_id := group_conf.get("area_id"):
            area_entities = await self.ctl.controller_hass.async_get_area_entities()
            area_entities = area_entities.get(group_area_id, {"entities": []})[
                "entities"
            ]
            for entity_id in area_entities:
                yield entity_id

        # Local group
        else:
            for light_id in group_conf["lights"]:
                entity_id = (
                    await self.ctl.config_instance.async_entity_id_from_light_id(
                        light_id
                    )
                )
                yield entity_id

    async def __async_whitelist_to_bridge_config(self) -> dict:
        whitelist = await self.ctl.config_instance.async_get_storage_value(
            "users", default={}
        )
        whitelist = copy.deepcopy(whitelist)
        for _username, data in whitelist.items():
            del data["username"]
            del data["clientkey"]
        return whitelist

    async def __async_get_bridge_config(self, full_details: bool = False) -> dict:
        """Return the (virtual) bridge configuration."""
        result = self.ctl.config_instance.definitions.get("bridge").get("basic").copy()
        result.update(
            {
                "name": self.ctl.config_instance.bridge_name,
                "mac": self.ctl.config_instance.mac_addr,
                "bridgeid": self.ctl.config_instance.bridge_id,
            }
        )
        if full_details:
            result.update(
                self.ctl.config_instance.definitions.get("bridge").get("full")
            )
            result.update(
                {
                    "linkbutton": self.ctl.config_instance.link_mode_enabled,
                    "ipaddress": self.ctl.config_instance.ip_addr,
                    "gateway": self.ctl.config_instance.ip_addr,
                    "UTC": datetime.datetime.utcnow().isoformat().split(".")[0],
                    "localtime": datetime.datetime.now().isoformat().split(".")[0],
                    "timezone": self.ctl.config_instance.get_storage_value(
                        "bridge_config", "timezone", tzlocal.get_localzone_name()
                    ),
                    "whitelist": await self.__async_whitelist_to_bridge_config(),
                    "zigbeechannel": self.ctl.config_instance.get_storage_value(
                        "bridge_config", "zigbeechannel", 25
                    ),
                }
            )
        return result
