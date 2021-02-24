"""Support for a Hue API to control Home Assistant."""
import copy
import datetime
import functools
import inspect
import json
import logging
import os
import ssl
import time
from typing import Any, AsyncGenerator, Optional

import emulated_hue.const as const
import tzlocal
from aiohttp import web
from emulated_hue.entertainment import EntertainmentAPI
from emulated_hue.ssl_cert import async_generate_selfsigned_cert, check_certificate
from emulated_hue.utils import (
    entity_attributes_to_int,
    send_error_response,
    send_json_response,
    send_success_response,
    update_dict,
)

LOGGER = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_static")
DESCRIPTION_FILE = os.path.join(STATIC_DIR, "description.xml")


class ClassRouteTableDef(web.RouteTableDef):
    """Allow decorators for route registering within class methods."""

    def __repr__(self) -> str:
        """Pretty-print Class."""
        return "<ClassRouteTableDef count={}>".format(len(self._items))

    def route(self, method: str, path: str, **kwargs):
        """Add route handler."""

        def inner(handler):
            handler.route_info = (method, path, kwargs)
            return handler

        return inner

    def add_class_routes(self, instance) -> None:
        """Collect routes from class methods."""

        def predicate(member) -> bool:
            return all(
                (inspect.iscoroutinefunction(member), hasattr(member, "route_info"))
            )

        for _, handler in inspect.getmembers(instance, predicate):
            method, path, kwargs = handler.route_info
            super().route(method, path, **kwargs)(handler)
            # also add the route with trailing slash,
            # the hue apps seem to be a bit inconsistent about that
            super().route(method, path + "/", **kwargs)(handler)


# pylint: disable=invalid-name
routes = ClassRouteTableDef()
# pylint: enable=invalid-name


def check_request(check_user=True, log_request=True):
    """Decorator: Some common logic to log and validate all requests."""

    def func_wrapper(func):
        @functools.wraps(func)
        async def wrapped_func(cls, request: web.Request):
            if log_request:
                LOGGER.debug("[%s] %s %s", request.remote, request.method, request.path)
            # check username
            if check_user:
                username = request.match_info.get("username")
                if not username or not await cls.config.async_get_user(username):
                    return send_error_response(request.path, "unauthorized user", 1)
            # check and unpack (json) body if needed
            if request.method in ["PUT", "POST"]:
                try:
                    request_data = await request.json()
                except ValueError:
                    request_data = await request.text()
                LOGGER.debug(request_data)
                return await func(cls, request, request_data)
            return await func(cls, request)

        return wrapped_func

    return func_wrapper


class HueApi:
    """Support for a Hue API to control Home Assistant."""

    runner = None

    def __init__(self, hue):
        """Initialize with Hue object."""
        self.streaming_api = None
        self.config = hue.config
        self.hue = hue
        self.http_site = None
        self.https_site = None
        self._new_lights = {}
        self._timestamps = {}
        self._prev_data = {}
        with open(DESCRIPTION_FILE, encoding="utf-8") as fdesc:
            self._description_xml = fdesc.read()

    async def async_setup(self):
        """Async set-up of the webserver."""
        app = web.Application()
        # add config routes
        app.router.add_route(
            "GET", "/api/{username}/config", self.async_get_bridge_config
        )
        app.router.add_route("GET", "/api/config", self.async_get_bridge_config)
        app.router.add_route(
            "GET", "/api/{username}/config/", self.async_get_bridge_config
        )
        app.router.add_route("GET", "/api/config/", self.async_get_bridge_config)
        # add all routes defined with decorator
        routes.add_class_routes(self)
        app.add_routes(routes)
        # Add catch-all handler for unknown requests to api
        app.router.add_route("*", "/api/{tail:.*}", self.async_unknown_request)
        # static files hosting
        app.router.add_static("/", STATIC_DIR, append_version=True)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()

        # Create and start the HTTP webserver/api
        self.http_site = web.TCPSite(self.runner, port=self.config.http_port)
        try:
            await self.http_site.start()
            LOGGER.info("Started HTTP webserver on port %s", self.config.http_port)
        except OSError as error:
            LOGGER.error(
                "Failed to create HTTP server at port %d: %s",
                self.config.http_port,
                error,
            )

        # create self signed certificate for HTTPS API
        cert_file = self.config.get_path(".cert.pem")
        key_file = self.config.get_path(".cert_key.pem")
        if not check_certificate(cert_file, self.config):
            await async_generate_selfsigned_cert(cert_file, key_file, self.config)
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)

        # Create and start the HTTPS webserver/API
        self.https_site = web.TCPSite(
            self.runner, port=self.config.https_port, ssl_context=ssl_context
        )
        try:
            await self.https_site.start()
            LOGGER.info("Started HTTPS webserver on port %s", self.config.https_port)
        except OSError as error:
            LOGGER.error(
                "Failed to create HTTPS server at port %d: %s",
                self.config.https_port,
                error,
            )

    async def async_stop(self):
        """Stop the webserver."""
        await self.http_site.stop()
        await self.https_site.stop()
        if self.streaming_api:
            self.streaming_api.stop()

    @routes.post("/api")
    @check_request(False)
    async def async_post_auth(self, request: web.Request, request_data: dict):
        """Handle requests to create a username for the emulated hue bridge."""
        if "devicetype" not in request_data:
            LOGGER.warning("devicetype not specified")
            # custom error message
            return send_error_response(request.path, "devicetype not specified", 302)
        if not self.config.link_mode_enabled:
            await self.config.async_enable_link_mode_discovery()
            return send_error_response(request.path, "link button not pressed", 101)

        userdetails = await self.config.async_create_user(request_data["devicetype"])
        response = [{"success": {"username": userdetails["username"]}}]
        if request_data.get("generateclientkey"):
            response[0]["success"]["clientkey"] = userdetails["clientkey"]
        LOGGER.info("Client %s registered", userdetails["name"])
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

        self.hue.loop.call_later(60, auto_disable)

        # enable all disabled lights and groups
        for entity in self.hue.hass.lights:
            entity_id = entity["entity_id"]
            light_id = await self.config.async_entity_id_to_light_id(entity_id)
            light_config = await self.config.async_get_light_config(light_id)
            if not light_config["enabled"]:
                light_config["enabled"] = True
                await self.config.async_set_storage_value(
                    "lights", light_id, light_config
                )
                # add to new_lights for the app to show a special badge
                self._new_lights[light_id] = await self.__async_entity_to_hue(
                    entity, light_config
                )
        groups = await self.config.async_get_storage_value("groups", default={})
        for group_id, group_conf in groups.items():
            if "enabled" in group_conf and not group_conf["enabled"]:
                group_conf["enabled"] = True
                await self.config.async_set_storage_value(
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
        entity = await self.config.async_entity_by_light_id(light_id)
        result = await self.__async_entity_to_hue(entity)
        return send_json_response(result)

    @routes.put("/api/{username}/lights/{light_id}/state")
    @check_request()
    async def async_put_light_state(self, request: web.Request, request_data: dict):
        """Handle requests to perform action on a group of lights/room."""
        light_id = request.match_info["light_id"]
        username = request.match_info["username"]
        entity = await self.config.async_entity_by_light_id(light_id)
        await self.__async_light_action(entity, request_data)
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
        group_id = request.match_info["group_id"]
        groups = await self.__async_get_all_groups()
        result = groups.get(group_id, {})
        return send_json_response(result)

    @routes.put("/api/{username}/groups/{group_id}/action")
    @check_request()
    async def async_group_action(self, request: web.Request, request_data: dict):
        """Handle requests to perform action on a group of lights/room."""
        group_id = request.match_info["group_id"]
        username = request.match_info["username"]
        # instead of directly getting groups should have a property
        # get groups instead so we can easily modify it
        group_conf = await self.config.async_get_storage_value("groups", group_id)
        if group_id == "0" and "scene" in request_data:
            # scene request
            scene = await self.config.async_get_storage_value(
                "scenes", request_data["scene"], default={}
            )
            for light_id, light_state in scene["lightstates"].items():
                entity = await self.config.async_entity_by_light_id(light_id)
                await self.__async_light_action(entity, light_state)
        else:
            # forward request to all group lights
            # may need refactor to make __async_get_group_lights not an
            # async generator to instead return a dict
            async for entity in self.__async_get_group_lights(group_id):
                await self.__async_light_action(entity, request_data)
        if group_conf and "stream" in group_conf:
            # Request streaming stop
            # Duplicate code here. Method instead?
            LOGGER.info(
                "Stop Entertainment mode for group %s - params: %s",
                group_id,
                request_data,
            )
            if self.streaming_api:
                # stop service if needed
                self.streaming_api.stop()
                self.streaming_api = None
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
        group_conf = await self.config.async_get_storage_value("groups", group_id)
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
                if not self.streaming_api:
                    user_data = await self.config.async_get_user(username)
                    self.streaming_api = EntertainmentAPI(
                        self.hue, group_conf, user_data
                    )
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
                if self.streaming_api:
                    # stop service if needed
                    self.streaming_api.stop()
                    self.streaming_api = None

        await self.config.async_set_storage_value("groups", group_id, group_conf)
        return send_success_response(request.path, request_data, username)

    @routes.put("/api/{username}/lights/{light_id}")
    @check_request()
    async def async_update_light(self, request: web.Request, request_data: dict):
        """Handle requests to update a light."""
        light_id = request.match_info["light_id"]
        username = request.match_info["username"]
        light_conf = await self.config.async_get_storage_value("lights", light_id)
        if not light_conf:
            return send_error_response(request.path, "no light config", 404)
        update_dict(light_conf, request_data)
        return send_success_response(request.path, request_data, username)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}")
    @check_request()
    async def async_get_localitems(self, request: web.Request):
        """Handle requests to retrieve localitems (e.g. scenes)."""
        itemtype = request.match_info["itemtype"]
        result = await self.config.async_get_storage_value(itemtype, default={})
        return send_json_response(result)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}/{item_id}")
    @check_request()
    async def async_get_localitem(self, request: web.Request):
        """Handle requests to retrieve info for a single localitem."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        items = await self.config.async_get_storage_value(itemtype)
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
        local_item = await self.config.async_get_storage_value(itemtype, item_id)
        if not local_item:
            return send_error_response(request.path, "no localitem", 404)
        update_dict(local_item, request_data)
        await self.config.async_set_storage_value(itemtype, item_id, local_item)
        return send_success_response(request.path, request_data, username)

    @routes.delete(
        "/api/{username}/{itemtype:(?:scenes|rules|resourcelinks|groups|lights)}/{item_id}"
    )
    @check_request()
    async def async_delete_localitem(self, request: web.Request):
        """Handle requests to delete a item from localstorage."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        await self.config.async_delete_storage_value(itemtype, item_id)
        result = [{"success": f"/{itemtype}/{item_id} deleted."}]
        return send_json_response(result)

    @check_request(check_user=False)
    async def async_get_bridge_config(self, request: web.Request):
        """Process a request to get (full or partial) config of this emulated bridge."""
        username = request.match_info.get("username")
        valid_user = True
        if not username or not await self.config.async_get_user(username):
            valid_user = False
            # discovery config requested, enable discovery request
            await self.config.async_enable_link_mode_discovery()
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
                if not self.config.link_mode_enabled:
                    await self.config.async_enable_link_mode()
            else:
                await self.config.async_set_storage_value("bridge_config", key, value)
        return send_success_response(request.path, request_data, username)

    async def async_scene_to_full_state(self) -> dict:
        """Return scene data, removing lightstates and adds group lights instead."""
        groups = await self.__async_get_all_groups()
        scenes = await self.config.async_get_storage_value("scenes", default={})
        scenes = copy.deepcopy(scenes)
        for scene_num, scene_data in scenes.items():
            scenes_group = scene_data["group"]
            del scene_data["lightstates"]
            scene_data["lights"] = groups[scenes_group]["lights"]
        return scenes

    @routes.get("/api/{username}")
    @check_request()
    async def get_full_state(self, request: web.Request):
        """Return full state view of emulated hue."""
        json_response = {
            "config": await self.__async_get_bridge_config(True),
            "schedules": await self.config.async_get_storage_value(
                "schedules", default={}
            ),
            "rules": await self.config.async_get_storage_value("rules", default={}),
            "scenes": await self.async_scene_to_full_state(),
            "resourcelinks": await self.config.async_get_storage_value(
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
            self.config.ip_addr,
            self.config.http_port,
            f"{self.config.bridge_name} ({self.config.ip_addr})",
            self.config.bridge_serial,
            self.config.bridge_uid,
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
            or not self.config.link_mode_discovery_key
            or token != self.config.link_mode_discovery_key
        ):
            return web.Response(body="Invalid token supplied!", status=302)
        html_template = """
            <html>
                <body>
                    <h2>Link mode is enabled for 5 minutes.</h2>
                </body>
            </html>"""
        await self.config.async_enable_link_mode()
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
            "timezones": {"value": self.config.definitions["timezones"]},
            "streaming": {"available": 1, "total": 10, "channels": 10},
        }

        return send_json_response(json_response)

    @routes.get("/api/{username}/info/timezones")
    @check_request()
    async def async_get_timezones(self, request: web.Request):
        """Return all timezones."""
        return send_json_response(self.config.definitions["timezones"])

    async def async_unknown_request(self, request: web.Request):
        """Handle unknown requests (catch-all)."""
        if request.method in ["PUT", "POST"]:
            try:
                request_data = await request.json()
            except json.decoder.JSONDecodeError:
                request_data = await request.text()
            LOGGER.warning("Invalid/unknown request: %s --> %s", request, request_data)
        else:
            LOGGER.warning("Invalid/unknown request: %s", request)
        return send_error_response(request.path, "unknown request", 404)

    async def __async_light_action(self, entity: dict, request_data: dict) -> None:
        """Translate the Hue api request data to actions on a light entity."""

        light_id = await self.config.async_entity_id_to_light_id(entity["entity_id"])
        light_conf = await self.config.async_get_light_config(light_id)
        throttle_ms = light_conf.get("throttle", const.DEFAULT_THROTTLE_MS)

        # Construct what we need to send to the service
        data = {const.HASS_ATTR_ENTITY_ID: entity["entity_id"]}

        power_on = request_data.get(const.HASS_STATE_ON, True)

        # throttle command to light
        data_with_power = request_data.copy()
        data_with_power[const.HASS_STATE_ON] = power_on
        if not self.__update_allowed(entity, data_with_power, throttle_ms):
            return

        service = (
            const.HASS_SERVICE_TURN_ON if power_on else const.HASS_SERVICE_TURN_OFF
        )
        if power_on:

            # set the brightness, hue, saturation and color temp
            if const.HUE_ATTR_BRI in request_data:
                # Prevent 0 brightness from turning light off
                request_bri = request_data[const.HUE_ATTR_BRI]
                if request_bri < const.HASS_ATTR_BRI_MIN:
                    request_bri = const.HASS_ATTR_BRI_MIN
                data[const.HASS_ATTR_BRIGHTNESS] = request_bri

            if const.HUE_ATTR_HUE in request_data or const.HUE_ATTR_SAT in request_data:
                hue = request_data.get(const.HUE_ATTR_HUE, 0)
                sat = request_data.get(const.HUE_ATTR_SAT, 0)
                # Convert hs values to hass hs values
                hue = int((hue / const.HUE_ATTR_HUE_MAX) * 360)
                sat = int((sat / const.HUE_ATTR_SAT_MAX) * 100)
                data[const.HASS_ATTR_HS_COLOR] = (hue, sat)

            if const.HUE_ATTR_CT in request_data:
                data[const.HASS_ATTR_COLOR_TEMP] = request_data[const.HUE_ATTR_CT]

            if const.HUE_ATTR_XY in request_data:
                data[const.HASS_ATTR_XY_COLOR] = request_data[const.HUE_ATTR_XY]

            if const.HUE_ATTR_EFFECT in request_data:
                data[const.HASS_ATTR_EFFECT] = request_data[const.HUE_ATTR_EFFECT]

            if const.HUE_ATTR_ALERT in request_data:
                if request_data[const.HUE_ATTR_ALERT] == "select":
                    data[const.HASS_ATTR_FLASH] = "short"
                elif request_data[const.HUE_ATTR_ALERT] == "lselect":
                    data[const.HASS_ATTR_FLASH] = "long"

        if const.HUE_ATTR_TRANSITION in request_data:
            # Duration of the transition from the light to the new state
            # is given as a multiple of 100ms and defaults to 4 (400ms).
            if request_data[const.HUE_ATTR_TRANSITION] * 100 <= throttle_ms:
                transitiontime = throttle_ms / 1000
            else:
                transitiontime = request_data[const.HUE_ATTR_TRANSITION] / 10
            data[const.HASS_ATTR_TRANSITION] = transitiontime
        else:
            data[const.HASS_ATTR_TRANSITION] = (
                0.4 if throttle_ms <= 400 else throttle_ms / 1000
            )

        # execute service
        await self.hue.hass.call_service(const.HASS_DOMAIN_LIGHT, service, data)

    def __update_allowed(
        self, entity: dict, light_data: dict, throttle_ms: int
    ) -> bool:
        """Minimalistic form of throttling, only allow updates to a light within a timespan."""

        if not throttle_ms:
            return True

        prev_data = self._prev_data.get(entity["entity_id"], {})

        # pass initial request to light
        if not prev_data:
            self._prev_data[entity["entity_id"]] = light_data.copy()
            return True

        # force to update if power state changed
        if (entity["state"] == const.HASS_STATE_ON) != light_data.get(
            const.HASS_STATE_ON, True
        ):
            self._prev_data[entity["entity_id"]].update(light_data)
            return True

        # check if data changed
        # when not using udp no need to send same light command again
        if (
            prev_data.get(const.HUE_ATTR_BRI, 0)
            == light_data.get(const.HUE_ATTR_BRI, 0)
            and prev_data.get(const.HUE_ATTR_HUE, 0)
            == light_data.get(const.HUE_ATTR_HUE, 0)
            and prev_data.get(const.HUE_ATTR_SAT, 0)
            == light_data.get(const.HUE_ATTR_SAT, 0)
            and prev_data.get(const.HUE_ATTR_CT, 0)
            == light_data.get(const.HUE_ATTR_CT, 0)
            and prev_data.get(const.HUE_ATTR_XY, [0, 0])
            == light_data.get(const.HUE_ATTR_XY, [0, 0])
            and prev_data.get(const.HUE_ATTR_EFFECT, "none")
            == light_data.get(const.HUE_ATTR_EFFECT, "none")
            and prev_data.get(const.HUE_ATTR_ALERT, "none")
            == light_data.get(const.HUE_ATTR_ALERT, "none")
        ):
            return False

        self._prev_data[entity["entity_id"]].update(light_data)

        # check throttle timestamp so light commands are only sent once every X milliseconds
        # this is to not overload a light implementation in Home Assistant
        prev_timestamp = self._timestamps.get(entity["entity_id"], 0)
        cur_timestamp = int(time.time() * 1000)
        time_diff = abs(cur_timestamp - prev_timestamp)
        if time_diff >= throttle_ms:
            # change allowed only if within throttle limit
            self._timestamps[entity["entity_id"]] = cur_timestamp
            return True
        return False

    async def __async_entity_to_hue(
        self, entity: dict, light_config: Optional[dict] = None
    ) -> dict:
        """Convert an entity to its Hue bridge JSON representation."""
        entity_attr = entity_attributes_to_int(entity["attributes"])
        entity_features = entity["attributes"].get(
            const.HASS_ATTR_SUPPORTED_FEATURES, 0
        )
        if not light_config:
            light_id = await self.config.async_entity_id_to_light_id(
                entity["entity_id"]
            )
            light_config = await self.config.async_get_light_config(light_id)

        retval = {
            "state": {
                const.HUE_ATTR_ON: entity["state"] == const.HASS_STATE_ON,
                "reachable": entity["state"] != const.HASS_STATE_UNAVAILABLE,
                "mode": "homeautomation",
            },
            "name": light_config["name"]
            or entity["attributes"].get("friendly_name", ""),
            "uniqueid": light_config["uniqueid"],
            "swupdate": {
                "state": "noupdates",
                "lastinstall": datetime.datetime.utcnow().isoformat().split(".")[0],
            },
            "config": light_config["config"],
        }

        # Determine correct Hue type from HA supported features
        if (
            (entity_features & const.HASS_SUPPORT_BRIGHTNESS)
            and (entity_features & const.HASS_SUPPORT_COLOR)
            and (entity_features & const.HASS_SUPPORT_COLOR_TEMP)
        ):
            # Extended Color light (Zigbee Device ID: 0x0210)
            # Same as Color light, but which supports additional setting of color temperature
            retval.update(self.hue.config.definitions["lights"]["Extended color light"])
            # get color temperature min/max values from HA attributes
            ct_min = entity_attr.get("min_mireds", 153)
            retval["capabilities"]["control"]["ct"]["min"] = ct_min
            ct_max = entity_attr.get("max_mireds", 500)
            retval["capabilities"]["control"]["ct"]["max"] = ct_max
            retval["state"].update(
                {
                    const.HUE_ATTR_BRI: entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0),
                    # TODO: remember last command to set colormode
                    const.HUE_ATTR_COLORMODE: const.HUE_ATTR_XY,
                    # TODO: add hue/sat
                    const.HUE_ATTR_XY: entity_attr.get(
                        const.HASS_ATTR_XY_COLOR, [0, 0]
                    ),
                    const.HUE_ATTR_HUE: entity_attr.get(
                        const.HASS_ATTR_HS_COLOR, [0, 0]
                    )[0],
                    const.HUE_ATTR_SAT: entity_attr.get(
                        const.HASS_ATTR_HS_COLOR, [0, 0]
                    )[1],
                    const.HUE_ATTR_CT: entity_attr.get(const.HASS_ATTR_COLOR_TEMP, 0),
                    const.HUE_ATTR_EFFECT: entity_attr.get(
                        const.HASS_ATTR_EFFECT, "none"
                    ),
                    const.HUE_ATTR_ALERT: "none",
                }
            )
        elif (entity_features & const.HASS_SUPPORT_BRIGHTNESS) and (
            entity_features & const.HASS_SUPPORT_COLOR
        ):
            # Color light (Zigbee Device ID: 0x0200)
            # Supports on/off, dimming and color control (hue/saturation, enhanced hue, color loop and XY)
            retval.update(self.hue.config.definitions["lights"]["Color light"])
            retval["state"].update(
                {
                    const.HUE_ATTR_BRI: entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0),
                    const.HUE_ATTR_COLORMODE: "xy",  # TODO: remember last command to set colormode
                    const.HUE_ATTR_XY: entity_attr.get(
                        const.HASS_ATTR_XY_COLOR, [0, 0]
                    ),
                    const.HUE_ATTR_HUE: entity_attr.get(
                        const.HASS_ATTR_HS_COLOR, [0, 0]
                    )[0],
                    const.HUE_ATTR_SAT: entity_attr.get(
                        const.HASS_ATTR_HS_COLOR, [0, 0]
                    )[1],
                    const.HUE_ATTR_EFFECT: "none",
                }
            )
        elif (entity_features & const.HASS_SUPPORT_BRIGHTNESS) and (
            entity_features & const.HASS_SUPPORT_COLOR_TEMP
        ):
            # Color temperature light (Zigbee Device ID: 0x0220)
            # Supports groups, scenes, on/off, dimming, and setting of a color temperature
            retval.update(
                self.hue.config.definitions["lights"]["Color temperature light"]
            )
            # get color temperature min/max values from HA attributes
            ct_min = entity_attr.get("min_mireds", 153)
            retval["capabilities"]["control"]["ct"]["min"] = ct_min
            ct_max = entity_attr.get("max_mireds", 500)
            retval["capabilities"]["control"]["ct"]["max"] = ct_max
            retval["state"].update(
                {
                    const.HUE_ATTR_BRI: entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0),
                    const.HUE_ATTR_COLORMODE: "ct",
                    const.HUE_ATTR_CT: entity_attr.get(const.HASS_ATTR_COLOR_TEMP, 0),
                }
            )
        elif entity_features & const.HASS_SUPPORT_BRIGHTNESS:
            # Dimmable light (Zigbee Device ID: 0x0100)
            # Supports groups, scenes, on/off and dimming
            brightness = entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0)
            retval["type"] = "Dimmable light"
            retval.update(self.hue.config.definitions["lights"]["Dimmable light"])
            retval["state"].update({const.HUE_ATTR_BRI: brightness})
        else:
            # On/off light (Zigbee Device ID: 0x0000)
            # Supports groups, scenes, on/off control
            retval.update(self.hue.config.definitions["lights"]["On/off light"])

        # Get device type, model etc. from the Hass device registry
        entity_attr = entity["attributes"]
        reg_entity = self.hue.hass.entity_registry.get(entity["entity_id"])
        if reg_entity and reg_entity["device_id"] is not None:
            device = self.hue.hass.device_registry.get(reg_entity["device_id"])
            if device:
                retval["manufacturername"] = device["manufacturer"]
                retval["modelid"] = device["model"]
                retval["productname"] = device["name"]
                if device["sw_version"]:
                    retval["swversion"] = device["sw_version"]
                if device["identifiers"]:
                    identifiers = device["identifiers"]
                    if isinstance(identifiers, dict):
                        # prefer real zigbee address if we have that
                        # might come in handy later when we want to
                        # send entertainment packets to the zigbee mesh
                        for key, value in device["identifiers"]:
                            if key == "zha":
                                retval["uniqueid"] = value
                    elif isinstance(identifiers, list):
                        # simply grab the first available identifier for now
                        # may inprove this in the future
                        for identifier in identifiers:
                            if isinstance(identifier, list):
                                retval["uniqueid"] = identifier[-1]
                                break
                            elif isinstance(identifier, str):
                                retval["uniqueid"] = identifier
                                break

        return retval

    async def __async_get_all_lights(self) -> dict:
        """Create a dict of all lights."""
        result = {}
        for entity in self.hue.hass.lights:
            entity_id = entity["entity_id"]
            light_id = await self.config.async_entity_id_to_light_id(entity_id)
            light_config = await self.config.async_get_light_config(light_id)
            if not light_config["enabled"]:
                continue
            result[light_id] = await self.__async_entity_to_hue(entity, light_config)
        return result

    async def __async_create_local_item(
        self, data: Any, itemtype: str = "scenes"
    ) -> str:
        """Create item in storage of given type (scenes etc.)."""
        local_items = await self.config.async_get_storage_value(itemtype, default={})
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
        await self.config.async_set_storage_value(itemtype, item_id, data)
        return item_id

    async def __async_get_all_groups(self) -> dict:
        """Create a dict of all groups."""
        result = {}

        # local groups first
        groups = await self.config.async_get_storage_value("groups", default={})
        for group_id, group_conf in groups.items():
            # no area_id = not hass area
            if "area_id" not in group_conf:
                if "stream" in group_conf:
                    group_conf = copy.deepcopy(group_conf)
                    if self.streaming_api:
                        group_conf["stream"]["active"] = True
                    else:
                        group_conf["stream"]["active"] = False
                result[group_id] = group_conf

        # Hass areas/rooms
        for area in self.hue.hass.area_registry.values():
            area_id = area["area_id"]
            group_id = await self.config.async_area_id_to_group_id(area_id)
            group_conf = await self.config.async_get_group_config(group_id)
            if not group_conf["enabled"]:
                continue
            result[group_id] = group_conf.copy()
            result[group_id]["lights"] = []
            result[group_id]["name"] = group_conf["name"] or area["name"]
            lights_on = 0
            # get all entities for this device
            async for entity in self.__async_get_group_lights(group_id):
                entity = self.hue.hass.get_state(entity["entity_id"], attribute=None)
                light_id = await self.config.async_entity_id_to_light_id(
                    entity["entity_id"]
                )
                result[group_id]["lights"].append(light_id)
                if entity["state"] == const.HASS_STATE_ON:
                    lights_on += 1
                    if lights_on == 1:
                        # set state of first light as group state
                        entity_obj = await self.__async_entity_to_hue(entity)
                        result[group_id]["action"] = entity_obj["state"]
            if lights_on > 0:
                result[group_id]["state"]["any_on"] = True
            if lights_on == len(result[group_id]["lights"]):
                result[group_id]["state"]["all_on"] = True
            # do not return empty areas/rooms
            if len(result[group_id]["lights"]) == 0:
                result.pop(group_id, None)

        return result

    async def __async_get_group_lights(
        self, group_id: str
    ) -> AsyncGenerator[dict, None]:
        """Get all light entities for a group."""
        if group_id == "0":
            all_lights = await self.__async_get_all_lights()
            group_conf = {}
            group_conf["lights"] = []
            for light_id in all_lights:
                group_conf["lights"].append(light_id)
        else:
            group_conf = await self.config.async_get_storage_value("groups", group_id)
        if not group_conf:
            raise RuntimeError("Invalid group id: %s" % group_id)

        # Hass group (area)
        if "area_id" in group_conf:
            for entity in self.hue.hass.entity_registry.values():
                if entity["disabled_by"]:
                    # do not include disabled devices
                    continue
                if not entity["entity_id"].startswith("light."):
                    # for now only include lights
                    # TODO: include switches, sensors ?
                    continue
                device = self.hue.hass.device_registry.get(entity["device_id"])
                # first check if area is defined on entity itself
                if entity["area_id"] and entity["area_id"] != group_conf["area_id"]:
                    # different area id defined on entity so skip this entity
                    continue
                elif entity["area_id"] == group_conf["area_id"]:
                    # our area_id is configured on the entity, use it
                    pass
                elif device and device["area_id"] == group_conf["area_id"]:
                    # our area_id is configured on the entity's device, use it
                    pass
                else:
                    continue
                # process the light entity
                light_id = await self.config.async_entity_id_to_light_id(
                    entity["entity_id"]
                )
                light_conf = await self.config.async_get_light_config(light_id)
                if not light_conf["enabled"]:
                    continue
                entity = self.hue.hass.get_state(entity["entity_id"], attribute=None)
                yield entity

        # Local group
        else:
            for light_id in group_conf["lights"]:
                entity = await self.config.async_entity_by_light_id(light_id)
                yield entity

    async def __async_whitelist_to_bridge_config(self) -> dict:
        whitelist = await self.config.async_get_storage_value("users", default={})
        whitelist = copy.deepcopy(whitelist)
        for username, data in whitelist.items():
            del data["username"]
            del data["clientkey"]
        return whitelist

    async def __async_get_bridge_config(self, full_details: bool = False) -> dict:
        """Return the (virtual) bridge configuration."""
        result = self.hue.config.definitions.get("bridge").get("basic").copy()
        result.update(
            {
                "name": self.config.bridge_name,
                "mac": self.config.mac_addr,
                "bridgeid": self.config.bridge_id,
            }
        )
        if full_details:
            result.update(self.hue.config.definitions.get("bridge").get("full"))
            result.update(
                {
                    "linkbutton": self.config.link_mode_enabled,
                    "ipaddress": self.config.ip_addr,
                    "gateway": self.config.ip_addr,
                    "UTC": datetime.datetime.utcnow().isoformat().split(".")[0],
                    "localtime": datetime.datetime.now().isoformat().split(".")[0],
                    "timezone": self.config.get_storage_value(
                        "bridge_config", "timezone", tzlocal.get_localzone().zone
                    ),
                    "whitelist": await self.__async_whitelist_to_bridge_config(),
                    "zigbeechannel": self.config.get_storage_value(
                        "bridge_config", "zigbeechannel", 25
                    ),
                }
            )
        return result
