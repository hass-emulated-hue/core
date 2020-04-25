"""Support for a Hue API to control Home Assistant."""
import datetime
import functools
import hashlib
import inspect
import logging
import os
import ssl

from aiohttp import web

from . import const, light_definitions
from .hue_entertainment import EntertainmentThread
from .ssl_cert import generate_selfsigned_cert
from .utils import slugify, update_dict

_LOGGER = logging.getLogger(__name__)


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


# pylint: disable=invalid-name
routes = ClassRouteTableDef()
# pylint: enable=invalid-name


def check_request(func):
    """Decorator: Some common logic to determine we got a valid request."""

    @functools.wraps(func)
    async def func_wrapper(cls, request):
        # check username
        if "username" in request.match_info:
            username = request.match_info["username"]
            if not await cls.config.get_user(username):
                return web.json_response(const.HUE_UNAUTHORIZED_USER)
        # check and unpack json body if needed
        if request.method in ["PUT", "POST"]:
            try:
                request_data = await request.json()
            except ValueError:
                return web.Response(body="Received invalid json!", status=404)
            return await func(cls, request, request_data)
        return await func(cls, request)

    return func_wrapper


class HueApi:
    """Support for a Hue API to control Home Assistant."""

    runner = None

    def __init__(self, hue):
        """Initialize with Hue object."""
        self.streaming_api = None
        self.config = hue.config
        self.hass = hue.hass
        self.hue = hue
        self.http_site = None
        self.https_site = None
        routes.add_class_routes(self)

    async def async_setup(self):
        """Async set-up of the webserver."""
        app = web.Application()
        # Add route for discovery info
        app.router.add_get("/api/nouser/config", self.get_discovery_config)
        # add all routes defined with decorator
        app.add_routes(routes)
        # Add catch-all handler for unkown requests
        app.router.add_route("*", "/{tail:.*}", self.unknown_request)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()

        # Create and start the HTTP API on port 80
        # Port MUST be 80 to maintain compatability with Hue apps
        self.http_site = web.TCPSite(
            self.runner, self.config.host_ip_addr, self.config.http_port
        )
        try:
            await self.http_site.start()
            _LOGGER.info("Started HTTP webserver on port %s", self.config.http_port)
        except OSError as error:
            _LOGGER.error(
                "Failed to create HTTP server at port %d: %s",
                self.config.http_port,
                error,
            )

        # create self signes certificate for HTTPS API
        cert_file = self.config.get_path(".cert.pem")
        key_file = self.config.get_path(".cert_key.pem")
        if not os.path.isfile(cert_file) or not os.path.isfile(key_file):
            generate_selfsigned_cert(cert_file, key_file, self.config)
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)

        # Create and start the HTTPS API on port 443
        # Port MUST be 443 to maintain compatability with Hue apps
        self.https_site = web.TCPSite(
            self.runner,
            self.config.host_ip_addr,
            self.config.https_port,
            ssl_context=ssl_context,
        )
        try:
            await self.https_site.start()
            _LOGGER.info("Started HTTPS webserver on port %s", self.config.https_port)
        except OSError as error:
            _LOGGER.error(
                "Failed to create HTTPS server at port %d: %s",
                self.config.https_port,
                error,
            )

    async def stop(self):
        """Stop the webserver."""
        await self.http_site.stop()
        await self.https_site.stop()
        if self.streaming_api:
            self.streaming_api.stop()

    @routes.get("/api{tail:/?}")
    @check_request
    async def get_auth(self, request):
        """Handle requests to find the emulated hue bridge."""
        return web.json_response(const.HUE_UNAUTHORIZED_USER)

    @routes.post("/api{tail:/?}")
    @check_request
    async def post_auth(self, request, request_data):
        """Handle requests to create a username for the emulated hue bridge."""
        if "devicetype" not in request_data:
            _LOGGER.warning("devicetype not specified")
            return web.json_response(("Devicetype not specified", 302))
        if not self.config.link_mode_enabled:
            _LOGGER.warning("Link mode is not enabled!")
            await self.config.enable_link_mode_discovery()
            return web.json_response(("Link mode is not enabled!", 302))
        userdetails = await self.config.create_user(request_data["devicetype"])
        response = [{"success": {"username": userdetails["username"]}}]
        if request_data.get("generateclientkey"):
            response[0]["success"]["clientkey"] = userdetails["clientkey"]
        _LOGGER.info("Client %s registered", userdetails["name"])
        return web.json_response(response)

    @routes.get("/api/{username}/lights")
    @check_request
    async def get_lights(self, request):
        """Handle requests to retrieve the info all lights."""
        return web.json_response(await self.__get_all_lights())

    @routes.get("/api/{username}/lights/new")
    @check_request
    async def get_light(self, request):
        """Handle requests to retrieve new added lights to the (virtual) bridge."""
        return web.json_response({})

    @routes.get("/api/{username}/lights/{light_id}")
    @check_request
    async def get_new_lights(self, request):
        """Handle requests to retrieve the info for a single light."""
        light_id = request.match_info["light_id"]
        entity = await self.config.entity_by_light_id(light_id)
        result = await self.__entity_to_json(entity)
        return web.json_response(result)

    @routes.put("/api/{username}/lights/{light_id}/state")
    @check_request
    async def put_light_state(self, request, request_data):
        """Handle requests to perform action on a group of lights/room."""
        light_id = request.match_info["light_id"]
        username = request.match_info["username"]
        entity = await self.config.entity_by_light_id(light_id)
        await self.__light_action(entity, request_data)
        # Create success responses for all received keys
        response = await self.__create_hue_response(
            request.path, request_data, username
        )
        return web.json_response(response)

    @routes.get("/api/{username}/groups")
    @check_request
    async def get_groups(self, request):
        """Handle requests to retrieve all rooms/groups."""
        groups = await self.__get_all_groups()
        return web.json_response(groups)

    @routes.get("/api/{username}/groups/{group_id}")
    @check_request
    async def get_group(self, request):
        """Handle requests to retrieve info for a single group."""
        group_id = request.match_info["group_id"]
        groups = await self.__get_all_groups()
        result = groups.get(group_id, {})
        return web.json_response(result)

    @routes.put("/api/{username}/groups/{group_id}/action")
    @check_request
    async def group_action(self, request, request_data):
        """Handle requests to perform action on a group of lights/room."""
        group_id = request.match_info["group_id"]
        username = request.match_info["username"]
        # forward request to all group lights
        async for entity in self.__get_group_lights(group_id):
            await self.__light_action(entity, request_data)
        # Create success responses for all received keys
        response = await self.__create_hue_response(
            request.path, request_data, username
        )
        return web.json_response(response)

    @routes.post("/api/{username}/groups")
    @check_request
    async def create_group(self, request, request_data):
        """Handle requests to create a new group."""
        item_id = await self.__create_local_item(request_data, "groups")
        return web.json_response([{"success": {"id": item_id}}])

    @routes.put("/api/{username}/groups/{group_id}")
    @check_request
    async def update_group(self, request, request_data):
        """Handle requests to update a group."""
        group_id = request.match_info["group_id"]
        username = request.match_info["username"]
        local_group = await self.config.get_storage_value("groups", group_id)
        if not local_group:
            return web.Response(status=404)
        update_dict(local_group, request_data)

        # Hue entertainment support (experimental)
        if "stream" in local_group:
            if local_group["stream"].get("active"):
                # Requested streaming start
                _LOGGER.debug(
                    "Start Entertainment mode for group %s - params: %s",
                    group_id,
                    request_data,
                )
                if not self.streaming_api:
                    user_data = await self.config.get_user(username)
                    self.streaming_api = EntertainmentThread(
                        self.hue, local_group, user_data
                    )
                    self.streaming_api.start()
                local_group["stream"]["owner"] = username
                if not local_group["stream"].get("proxymode"):
                    local_group["stream"]["proxymode"] = "auto"
                if not local_group["stream"].get("proxynode"):
                    local_group["stream"]["proxynode"] = "/bridge"
            else:
                # Request streaming stop
                _LOGGER.info(
                    "Stop Entertainment mode for group %s - params: %s",
                    group_id,
                    request_data,
                )
                local_group["stream"] = {"active": False}
                if self.streaming_api:
                    # stop service if needed
                    self.streaming_api.stop()
                    self.streaming_api = None

        await self.config.set_storage_value("groups", group_id, local_group)
        response = await self.__create_hue_response(
            request.path, request_data, username
        )
        return web.json_response(response)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}")
    @check_request
    async def get_localitems(self, request):
        """Handle requests to retrieve localitems (e.g. scenes)."""
        itemtype = request.match_info["itemtype"]
        result = await self.config.get_storage_value(itemtype)
        return web.json_response(result)

    @routes.get("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}/{item_id}")
    @check_request
    async def get_localitem(self, request):
        """Handle requests to retrieve info for a single localitem."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        items = await self.config.get_storage_value(itemtype)
        result = items.get(item_id, {})
        return web.json_response(result)

    @routes.post("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}")
    @check_request
    async def create_localitem(self, request, request_data):
        """Handle requests to create a new localitem."""
        itemtype = request.match_info["itemtype"]
        item_id = await self.__create_local_item(request_data, itemtype)
        return web.json_response([{"success": {"id": item_id}}])

    @routes.put("/api/{username}/{itemtype:(?:scenes|rules|resourcelinks)}/{item_id}")
    @check_request
    async def update_localitem(self, request, request_data):
        """Handle requests to update an item in localstorage."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        username = request.match_info["username"]
        local_item = await self.config.get_storage_value(itemtype, item_id)
        if not local_item:
            return web.Response(status=404)
        update_dict(local_item, request_data)
        await self.config.set_storage_value(itemtype, item_id, local_item)
        response = await self.__create_hue_response(
            request.path, request_data, username
        )
        return web.json_response(response)

    @routes.delete(
        "/api/{username}/{itemtype:(?:scenes|rules|resourcelinks|groups)}/{item_id}"
    )
    @check_request
    async def delete_localitem(self, request):
        """Handle requests to delete a item from localstorage."""
        item_id = request.match_info["item_id"]
        itemtype = request.match_info["itemtype"]
        await self.config.delete_storage_value(itemtype, item_id)
        result = [{"success": f"/{itemtype}/{item_id} deleted."}]
        return web.json_response(result)

    @check_request
    async def get_discovery_config(self, request):
        """Process a request to get the (basic) config of this emulated bridge."""
        await self.config.enable_link_mode_discovery()
        result = await self.__get_bridge_config(False)
        return web.json_response(result)

    @routes.get("/api/{username}/config")
    @check_request
    async def get_config(self, request):
        """Process a request to get the (full) config of this emulated bridge."""
        result = await self.__get_bridge_config(True)
        return web.json_response(result)

    @routes.put("/api/{username}/config")
    @check_request
    async def change_config(self, request, request_data):
        """Process a request to change a config value."""
        username = request.match_info["username"]
        # just log this request and return succes
        _LOGGER.debug("Change config called with params: %s", request_data)
        response = await self.__create_hue_response(
            request.path, request_data, username
        )
        return web.json_response(response)

    @routes.get("/api/{username}{tail:/?}")
    @check_request
    async def get_full_state(self, request):
        """Return full state view of emulated hue."""
        json_response = {
            "config": await self.__get_bridge_config(False),
            "schedules": await self.config.get_storage_value("schedules"),
            "rules": await self.config.get_storage_value("rules"),
            "scenes": await self.config.get_storage_value("scenes"),
            "resourcelinks": await self.config.get_storage_value("resourcelinks"),
            "lights": await self.__get_all_lights(),
            "groups": await self.__get_all_groups(),
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
                    "manufacturername": "Philips",
                    "swversion": "1.0",
                }
            },
        }

        return web.json_response(json_response)

    @routes.get("/api/{username}/sensors")
    @check_request
    async def get_sensors(self, request):
        """Return sensors on the (virtual) bridge."""
        # not supported yet but prevent errors
        return web.json_response({})

    @routes.get("/api/{username}/sensors/new")
    @check_request
    async def get_new_sensors(self, request):
        """Return all new discovered sensors on the (virtual) bridge."""
        # not supported yet but prevent errors
        return web.json_response({})

    @routes.get("/description.xml")
    @check_request
    async def get_description(self, request):
        """Serve the service description file."""
        xml_template = """
            <?xml version="1.0" encoding="UTF-8" ?>
                <root xmlns="urn:schemas-upnp-org:device-1-0">
                    <specVersion>
                    <major>1</major>
                    <minor>0</minor>
                    </specVersion>
                    <URLBase>http://{0}:{1}/</URLBase>
                    <device>
                    <deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>
                    <friendlyName>Home Assistant Bridge ({0})</friendlyName>
                    <manufacturer>Royal Philips Electronics</manufacturer>
                    <manufacturerURL>http://www.philips.com</manufacturerURL>
                    <modelDescription>Philips hue Personal Wireless Lighting</modelDescription>
                    <modelName>Philips hue bridge 2015</modelName>
                    <modelNumber>BSB002</modelNumber>
                    <modelURL>http://www.meethue.com</modelURL>
                    <serialNumber>{0}</serialNumber>
                    <UDN>uuid:{0}</UDN>
                    </device>
                </root>"""
        resp_text = xml_template.format(
            self.config.host_ip_addr,
            self.config.http_port,
            self.config.bridge_id,
            self.config.bridge_uid,
        )
        return web.Response(text=resp_text, content_type="text/xml")

    @routes.get("/link")
    @check_request
    async def link(self, request):
        """Enable link mode on the bridge."""
        token = request.rel_url.query.get("token")
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
                    <h2>Link mode is enabled for 30 seconds.</h2>
                </body>
            </html>"""
        await self.config.enable_link_mode()
        return web.Response(text=html_template, content_type="text/html")

    @routes.get("/api/{username}/capabilities")
    @check_request
    async def get_capabilities(self, request):
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
            "timezones": {"values": []},
            "streaming": {"available": 1, "total": 10, "channels": 10},
        }

        return web.json_response(json_response)

    async def unknown_request(self, request):
        """Handle unknown requests (catch-all)."""
        if request.method in ["PUT", "POST"]:
            request_data = await request.json()
            _LOGGER.warning("Invalid request: %s --> %s", request, request_data)
        else:
            _LOGGER.warning("Invalid request: %s", request)
        return web.Response(status=404)

    async def __light_action(self, entity, request_data):
        """Translate the Hue api request data to actions on a light entity."""

        # Construct what we need to send to the service
        data = {const.HASS_ATTR_ENTITY_ID: entity["entity_id"]}

        power_on = request_data.get(const.HASS_STATE_ON, True)
        service = (
            const.HASS_SERVICE_TURN_ON if power_on else const.HASS_SERVICE_TURN_OFF
        )
        if power_on:

            # set the brightness, hue, saturation and color temp
            if const.HUE_ATTR_BRI in request_data:
                data[const.HASS_ATTR_BRIGHTNESS] = request_data[const.HUE_ATTR_BRI]

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
            transitiontime = request_data[const.HUE_ATTR_TRANSITION] / 100
            data[const.HASS_ATTR_TRANSITION] = transitiontime

        # execute service
        await self.hass.call_service(const.HASS_DOMAIN_LIGHT, service, data)

    async def __entity_to_json(self, entity):
        """Convert an entity to its Hue bridge JSON representation."""
        entity_features = entity["attributes"].get(
            const.HASS_ATTR_SUPPORTED_FEATURES, 0
        )
        unique_id = hashlib.md5(entity["entity_id"].encode()).hexdigest()
        unique_id = "00:{}:{}:{}:{}:{}:{}:{}-{}".format(
            unique_id[0:2],
            unique_id[2:4],
            unique_id[4:6],
            unique_id[6:8],
            unique_id[8:10],
            unique_id[10:12],
            unique_id[12:14],
            unique_id[14:16],
        )

        retval = {
            "state": {
                const.HUE_ATTR_ON: entity["state"] == const.HASS_STATE_ON,
                "reachable": entity["state"] != const.HASS_STATE_UNAVAILABLE,
                "mode": "homeautomation",
            },
            "name": entity["attributes"].get("friendly_name", ""),
            "uniqueid": unique_id,
            "manufacturername": "Home Assistant",
            "productname": "Emulated Hue",
            "modelid": entity["entity_id"],
            "swversion": "5.127.1.26581",
        }

        # get device type, model etc. from the Hass device registry
        entity_attr = entity["attributes"]
        reg_entity = self.hass.entity_registry.get(entity["entity_id"])
        if reg_entity and reg_entity["device_id"] is not None:
            device = self.hass.device_registry.get(reg_entity["device_id"])
            if device:
                retval["manufacturername"] = device["manufacturer"]
                retval["modelid"] = device["model"]
                retval["productname"] = device["name"]
                if device["sw_version"]:
                    retval["swversion"] = device["sw_version"]

        if (
            (entity_features & const.HASS_SUPPORT_BRIGHTNESS)
            and (entity_features & const.HASS_SUPPORT_COLOR)
            and (entity_features & const.HASS_SUPPORT_COLOR_TEMP)
        ):
            # Extended Color light (Zigbee Device ID: 0x0210)
            # Same as Color light, but which supports additional setting of color temperature
            retval["type"] = "Extended color light"
            retval["state"].update(
                {
                    const.HUE_ATTR_BRI: entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0),
                    # TODO: remember last command to set colormode
                    const.HUE_ATTR_COLORMODE: const.HUE_ATTR_XY,
                    const.HUE_ATTR_XY: entity_attr.get(
                        const.HASS_ATTR_XY_COLOR, [0, 0]
                    ),
                    const.HUE_ATTR_CT: entity_attr.get(const.HASS_ATTR_COLOR_TEMP, 0),
                    const.HUE_ATTR_EFFECT: entity_attr.get(
                        const.HASS_ATTR_EFFECT, "none"
                    ),
                }
            )
        elif (entity_features & const.HASS_SUPPORT_BRIGHTNESS) and (
            entity_features & const.HASS_SUPPORT_COLOR
        ):
            # Color light (Zigbee Device ID: 0x0200)
            # Supports on/off, dimming and color control (hue/saturation, enhanced hue, color loop and XY)
            retval["type"] = "Color light"
            retval["state"].update(
                {
                    const.HUE_ATTR_BRI: entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0),
                    const.HUE_ATTR_COLORMODE: "xy",  # TODO: remember last command to set colormode
                    const.HUE_ATTR_XY: entity_attr.get(
                        const.HASS_ATTR_XY_COLOR, [0, 0]
                    ),
                    const.HUE_ATTR_EFFECT: "none",
                }
            )
        elif (entity_features & const.HASS_SUPPORT_BRIGHTNESS) and (
            entity_features & const.HASS_SUPPORT_COLOR_TEMP
        ):
            # Color temperature light (Zigbee Device ID: 0x0220)
            # Supports groups, scenes, on/off, dimming, and setting of a color temperature
            retval["type"] = "Color temperature light"
            retval["state"].update(
                {
                    const.HUE_ATTR_COLORMODE: "ct",
                    const.HUE_ATTR_CT: entity_attr.get(const.HASS_ATTR_COLOR_TEMP, 0),
                }
            )
        elif entity_features & const.HASS_SUPPORT_BRIGHTNESS:
            # Dimmable light (Zigbee Device ID: 0x0100)
            # Supports groups, scenes, on/off and dimming
            brightness = entity_attr.get(const.HASS_ATTR_BRIGHTNESS, 0)
            retval["type"] = "Dimmable light"
            retval["state"].update({const.HUE_ATTR_BRI: brightness})
        else:
            # On/off light (Zigbee Device ID: 0x0000)
            # Supports groups, scenes, on/off control
            retval["type"] = "On/off light"

        # append advanced model info (Official Philips lights connected by ZHA)
        model_slug = slugify(retval["modelid"]).upper()
        model_info = getattr(light_definitions, model_slug, None)
        if model_info:
            retval.update(model_info)

        return retval

    async def __create_hue_response(self, request_path, request_data, username):
        """Create success responses for all received keys."""
        request_path = request_path.replace(f"/api/{username}", "")
        json_response = []
        for key, val in request_data.items():
            obj_path = f"{request_path}/{key}"
            if "/groups" in obj_path:
                item = {"success": {"address": obj_path, "value": val}}
            else:
                item = {"success": {obj_path: val}}
            json_response.append(item)
        return json_response

    async def __get_all_lights(self):
        """Create a list of all lights."""
        result = {}
        for entity in await self.hass.lights():
            entity_id = entity["entity_id"]
            light_id = await self.config.entity_id_to_light_id(entity_id)
            result[light_id] = await self.__entity_to_json(entity)
        return result

    async def __create_local_item(self, data, itemtype="scenes"):
        """Create item in storage of given type (scenes etc.)."""
        local_items = await self.config.get_storage_value(itemtype)
        # get first available id
        for i in range(1, 1000):
            item_id = str(i)
            if item_id not in local_items:
                break
        await self.config.set_storage_value(itemtype, item_id, data)
        return item_id

    async def __get_all_groups(self):
        """Create a list of all groups."""
        result = {}

        # local groups first
        local_groups = await self.config.get_storage_value("groups")
        result.update(local_groups)

        # Hass areas/rooms
        for area in self.hass.area_registry.values():
            area_id = area["area_id"]
            group_id = await self.config.entity_id_to_light_id(area_id)
            group_conf = result[group_id] = {
                "class": "Other",
                "type": "Room",
                "name": area["name"],
                "lights": [],
                "sensors": [],
                "action": {"on": False},
                "state": {"any_on": False, "all_on": False},
            }
            lights_on = 0
            # get all entities for this device
            async for entity in self.__get_group_lights(group_id):
                entity = await self.hass.get_state(entity["entity_id"])
                light_id = await self.config.entity_id_to_light_id(entity["entity_id"])
                group_conf["lights"].append(light_id)
                if entity["state"] == const.HASS_STATE_ON:
                    lights_on += 1
                    if lights_on == 1:
                        # set state of first light as group state
                        entity_obj = await self.__entity_to_json(entity)
                        group_conf["action"] = entity_obj["state"]
            if lights_on > 0:
                group_conf["state"]["any_on"] = True
            if lights_on == len(group_conf["lights"]):
                group_conf["state"]["all_on"] = True

        return result

    async def __get_group_lights(self, group_id):
        """Get all light entities for a group."""
        # try local groups first
        local_groups = await self.config.get_storage_value("groups")
        if group_id in local_groups:
            local_group = local_groups[group_id]
            for light_id in local_group["lights"]:
                entity = await self.config.entity_by_light_id(light_id)
                yield entity

        # fall back to hass groups (areas)
        else:
            area_id = await self.config.light_id_to_entity_id(group_id)
            for device in self.hass.device_registry.values():
                if device["area_id"] != area_id:
                    continue
                # get all entities for this device
                for entity in self.hass.entity_registry.values():
                    if entity["device_id"] != device["id"] or entity["disabled_by"]:
                        continue
                    if not entity["entity_id"].startswith("light."):
                        continue
                    entity = await self.hass.get_state(entity["entity_id"])
                    yield entity

    async def __get_bridge_config(self, full_details=False):
        """Return the (virtual) bridge configuration."""
        result = {
            "name": "Home Assistant",
            "datastoreversion": 70,
            "swversion": "1937113020",
            "apiversion": "1.35.0",
            "mac": self.config.mac_addr,
            "bridgeid": self.config.bridge_id,
            "factorynew": False,
            "replacesbridgeid": None,
            "modelid": "BSB002",
            "starterkitid": "",
        }
        if full_details:
            result.update(
                {
                    "backup": {"errorcode": 0, "status": "idle"},
                    "datastoreversion": "70",
                    "dhcp": True,
                    "internetservices": {
                        "internet": "connected",
                        "remoteaccess": "connected",
                        "swupdate": "connected",
                        "time": "connected",
                    },
                    "netmask": "255.255.255.0",
                    "gateway": self.config.host_ip_addr,
                    "proxyport": 0,
                    "UTC": datetime.datetime.now().isoformat().split(".")[0],
                    "timezone": "Europe/Amsterdam",
                    "portalconnection": "connected",
                    "portalservices": True,
                    "portalstate": {
                        "communication": "disconnected",
                        "incoming": False,
                        "outgoing": False,
                        "signedon": True,
                    },
                    "swupdate": {
                        "checkforupdate": False,
                        "devicetypes": {"bridge": False, "lights": [], "sensors": []},
                        "notify": True,
                        "text": "",
                        "updatestate": 0,
                        "url": "",
                    },
                    "swupdate2": {
                        "checkforupdate": False,
                        "lastchange": "2018-06-09T10:11:08",
                        "bridge": {
                            "state": "noupdates",
                            "lastinstall": "2018-06-08T19:09:45",
                        },
                        "state": "noupdates",
                        "autoinstall": {"updatetime": "T14:00:00", "on": False},
                    },
                    "whitelist": await self.config.get_storage_value("users"),
                    "zigbeechannel": 25,
                    "linkbutton": self.config.link_mode_enabled,
                }
            )
        return result
