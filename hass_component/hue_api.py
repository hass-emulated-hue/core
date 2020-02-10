"""Support for a Hue API to control Home Assistant."""
from aiohttp import web
import hashlib
import logging
import functools

from homeassistant import core
from homeassistant.components import light, switch
from homeassistant.components.http.const import KEY_REAL_IP
from homeassistant.util import slugify
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_XY_COLOR,
    ATTR_HS_COLOR,
    ATTR_EFFECT,
    ATTR_TRANSITION,
    ATTR_FLASH,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    HTTP_UNAUTHORIZED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.util.network import is_local
from . import light_definitions
from .hue_entertainment import EntertainmentThread

_LOGGER = logging.getLogger(__name__)

# Hue API states
HUE_API_ATTR_ON = "on"
HUE_API_ATTR_BRI = "bri"
HUE_API_ATTR_COLORMODE = "colormode"
HUE_API_ATTR_HUE = "hue"
HUE_API_ATTR_SAT = "sat"
HUE_API_ATTR_CT = "ct"
HUE_API_ATTR_XY = "xy"
HUE_API_ATTR_EFFECT = "effect"
HUE_API_ATTR_TRANSITION = "transitiontime"
HUE_API_ATTR_ALERT = "alert"

# Hue API min/max values - https://developers.meethue.com/develop/hue-api/lights-api/
HUE_API_ATTR_BRI_MIN = 1  # Brightness
HUE_API_ATTR_BRI_MAX = 254
HUE_API_ATTR_HUE_MIN = 0  # Hue
HUE_API_ATTR_HUE_MAX = 65535
HUE_API_ATTR_SAT_MIN = 0  # Saturation
HUE_API_ATTR_SAT_MAX = 254
HUE_API_ATTR_CT_MIN = 153  # Color temp
HUE_API_ATTR_CT_MAX = 500

HUE_API_USERNAME = "12345678901234567890"
HUE_API_CLIENT_KEY = "321c0c2ebfa7361e55491095b2f5f9db"
HUE_API_UNAUTHORIZED_USER = [
    {"error": {"address": "/", "description": "unauthorized user", "type": "1"}}
]

routes = web.RouteTableDef()


def check_request(func):
    """Decorator: Some common logic to determine we got a valid request."""
    @functools.wraps(func)
    async def func_wrapper(request):
        # check username
        if "username" in request.match_info and request.match_info["username"] != HUE_API_USERNAME:
            return web.json_response(HUE_API_UNAUTHORIZED_USER)
        # only local calls alllowed
        if not is_local(request[KEY_REAL_IP]):
            return web.Response(body="Only local IPs allowed", status=HTTP_UNAUTHORIZED)
        # check and unpack json body if needed
        if request.method in ["PUT", "POST"]:
            try:
                request_data = await request.json()
            except ValueError:
                return web.Response(body="Received invalid json!", status=404)
            #_LOGGER.debug("%s --> %s", request, request_data)
            return await func(request, request_data)
        return await func(request)
    return func_wrapper


def update_dict(dict1, dict2):
    """Helper to update dict1 with values of dict2."""
    for key, value in dict2.items():
        if key in dict1 and isinstance(value, dict):
            update_dict(dict1[key], value)
        else:
            dict1[key] = value


@routes.get('/api')
@routes.get('/api/')
@check_request
async def get_auth(request):
    """Handle requests to find the emulated hue bridge."""
    return web.json_response(HUE_API_UNAUTHORIZED_USER)


@routes.post('/api/')
@routes.post('/api')
@check_request
async def post_auth(request, request_data):
    """Handle requests to create a username for the emulated hue bridge."""
    if "devicetype" not in request_data:
        _LOGGER.warning("devicetype not specified")
        return web.json_response(("devicetype not specified", HTTP_BAD_REQUEST))
    response = [{"success": {"username": HUE_API_USERNAME}}]
    if request_data.get("generateclientkey"):
        response[0]["success"]["clientkey"] = HUE_API_CLIENT_KEY
    _LOGGER.info("New client app registered: %s", response[0]["success"])
    return web.json_response(response)


@routes.get('/api/{username}/lights')
@check_request
async def get_lights(request):
    """Handle requests to retrieve the info all lights."""
    return web.json_response(await __get_all_lights(request))


@routes.get('/api/{username}/lights/new')
@check_request
async def get_light(request):
    """Handle requests to retrieve new added lights to the (virtual) bridge."""
    return web.json_response({})


@routes.get('/api/{username}/lights/{light_id}')
@check_request
async def get_new_lights(request):
    """Handle requests to retrieve the info for a single light."""
    light_id = request.match_info['light_id']
    config = request.app["config"]
    entity = await config.entity_by_light_id(light_id)
    result = await __entity_to_json(config, entity)
    return web.json_response(result)


@routes.put('/api/{username}/lights/{light_id}/state')
@check_request
async def put_light_state(request, request_data):
    """Handle requests to perform action on a group of lights/room."""
    light_id = request.match_info['light_id']
    hass = request.app["hass"]
    config = request.app["config"]
    entity = await config.entity_by_light_id(light_id)
    await __light_action(hass, entity, request_data)
    # Create success responses for all received keys
    response = await __create_hue_response(request.path, request_data)
    return web.json_response(response)


@routes.get('/api/{username}/groups')
@check_request
async def get_groups(request):
    """Handle requests to retrieve all rooms/groups."""
    groups = await __get_all_groups(request)
    return web.json_response(groups)


@routes.get('/api/{username}/groups/{group_id}')
@check_request
async def get_group(request):
    """Handle requests to retrieve info for a single group."""
    group_id = request.match_info['group_id']
    groups = await __get_all_groups(request)
    result = groups.get(group_id, {})
    return web.json_response(result)


@routes.put('/api/{username}/groups/{group_id}/action')
@check_request
async def group_action(request, request_data):
    """Handle requests to perform action on a group of lights/room."""
    group_id = request.match_info['group_id']
    hass = request.app["hass"]
    config = request.app["config"]
    # forward request to all group lights
    async for entity in __get_group_lights(config, group_id):
        await __light_action(hass, entity, request_data)
    # Create success responses for all received keys
    response = await __create_hue_response(request.path, request_data)
    return web.json_response(response)


@routes.post('/api/{username}/groups')
@check_request
async def create_group(request, request_data):
    """Handle requests to create a new group."""
    config = request.app["config"]
    item_id = await __create_local_item(config, request_data, "groups")
    return web.json_response([{"success": {"id": item_id}}])


@routes.put('/api/{username}/groups/{group_id}')
@check_request
async def update_group(request, request_data):
    """Handle requests to update a group."""
    group_id = request.match_info['group_id']
    config = request.app["config"]
    hass = request.app["hass"]
    local_groups = await config.get_storage_value("groups", {})
    if not group_id in local_groups:
        return web.Response(status=404)
    local_group = local_groups[group_id]
    update_dict(local_group, request_data)

    # Hue entertainment support (experimental)
    if "stream" in local_group:
        if local_group["stream"].get("active"):
            # Requested streaming start
            _LOGGER.info("Start Entertainment mode for group %s - params: %s", group_id, request_data)
            if not request.app["entertainment"]:
                request.app["entertainment"] = EntertainmentThread(
                    hass, config, local_group)
                request.app["entertainment"].start()
            if not local_group["stream"].get("owner"):
                local_group["stream"]["owner"] = HUE_API_USERNAME
            if not local_group["stream"].get("proxymode"):
                local_group["stream"]["proxymode"] = "auto"
            if not local_group["stream"].get("proxynode"):
                local_group["stream"]["proxynode"] = "/bridge"
        else:
             # Request streaming stop
            _LOGGER.info("Stop Entertainment mode for group %s - params: %s", group_id, request_data)
            local_group["stream"] = {"active": False}
            if request.app["entertainment"]:
               # stop service if needed
                request.app["entertainment"].stop()
                request.app["entertainment"] = None

    await config.set_storage_value("groups", local_groups)
    response = await __create_hue_response(request.path, request_data)
    return web.json_response(response)


@routes.get('/api/{username}/scenes')
@routes.get('/api/{username}/rules')
@routes.get('/api/{username}/resourcelinks')
@check_request
async def get_localitems(request):
    """Handle requests to retrieve localitems (e.g. scenes)."""
    itemtype = request.path.split("/")[3]
    result = await __get_local_items(request.app["config"], itemtype)
    return web.json_response(result)


@routes.get('/api/{username}/scenes/{item_id}')
@routes.get('/api/{username}/rules/{item_id}')
@routes.get('/api/{username}/resourcelinks/{item_id}')
@check_request
async def get_localitem(request):
    """Handle requests to retrieve info for a single localitem."""
    item_id = request.match_info['item_id']
    itemtype = request.path.split("/")[3]
    items = await __get_local_items(request.app["config"], itemtype)
    result = items.get(item_id, {})
    return web.json_response(result)


@routes.post('/api/{username}/scenes')
@routes.post('/api/{username}/rules')
@routes.post('/api/{username}/resourcelinks')
@check_request
async def create_localitem(request, request_data):
    """Handle requests to create a new localitem."""
    config = request.app["config"]
    itemtype = request.path.split("/")[3]
    item_id = await __create_local_item(config, request_data, itemtype)
    return web.json_response([{"success": {"id": item_id}}])


@routes.put('/api/{username}/scenes/{item_id}')
@routes.put('/api/{username}/rules/{item_id}')
@routes.put('/api/{username}/resourcelinks/{item_id}')
@check_request
async def update_localitem(request, request_data):
    """Handle requests to update an item in localstorage."""
    item_id = request.match_info['item_id']
    itemtype = request.path.split("/")[3]
    config = request.app["config"]
    local_items = await __get_local_items(config, itemtype)
    if not item_id in local_items:
        return web.Response(status=302)
    update_dict(local_items, request_data)
    await config.set_storage_value(itemtype, local_items)
    response = await __create_hue_response(request.path, request_data)
    return web.json_response(response)


@routes.delete('/api/{username}/groups/{item_id}')
@routes.delete('/api/{username}/scenes/{item_id}')
@routes.delete('/api/{username}/rules/{item_id}')
@routes.delete('/api/{username}/resourcelinks/{item_id}')
@check_request
async def delete_localitem(request):
    """Handle requests to delete a item from localstorage."""
    item_id = request.match_info['item_id']
    itemtype = request.path.split("/")[3]
    config = request.app["config"]
    local_items = await __get_local_items(config, itemtype)
    if not item_id in local_items:
        return web.Response(status=302)
    local_items.pop(item_id, None)
    await config.set_storage_value(itemtype, local_items)
    result = [{"success": f"/{itemtype}/{item_id} deleted."}]
    return web.json_response(result)


@routes.get('/api/nouser/config')
@check_request
async def get_discovery_config(request):
    """Process a request to get the (basic) config of this emulated bridge."""
    result = await __get_bridge_config(request)
    return web.json_response(result)


@routes.get('/api/{username}/config')
@check_request
async def get_config(request):
    """Process a request to get the (full) config of this emulated bridge."""
    result = await __get_bridge_config(request, True)
    return web.json_response(result)


@routes.get('/api/{username}')
@routes.get('/api/{username}/')
@check_request
async def get_full_state(request):
    """Return full state view of emulated hue."""
    config = request.app["config"]
    json_response = {
        "config": await __get_bridge_config(request, True),
        "schedules": await __get_local_items(config, "schedules"),
        "rules": await __get_local_items(config, "rules"),
        "scenes": await __get_local_items(config, "scenes"),
        "resourcelinks": await __get_local_items(config, "resourcelinks"),
        "lights": await __get_all_lights(request),
        "groups": await __get_all_groups(request),
        "sensors": {}  # TODO?
    }
    return web.json_response(json_response)


@routes.get('/api/{username}/sensors')
@routes.get('/api/{username}/sensors/new')
@check_request
async def get_sensors(request):
    """Return sensors on the (virtual) bridge."""
    # not supported yet but prevent errors
    return web.json_response({})


@routes.get('/description.xml')
@check_request
async def get_description(request):
    """Serve the service description file."""
    config = request.app["config"]
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
        config.advertise_ip, config.advertise_port, config.bridge_id, config.bridge_uid)
    return web.Response(text=resp_text, content_type="text/xml")


@routes.get('/api/{username}/capabilities')
@check_request
async def get_capabilities(request):
    """Return an overview of the capabilities."""
    streaming_available = 0 if request.app["entertainment"] else 1
    json_response = {
        "lights": {"available": 100},
        "sensors": {
            "available": 60,
            "clip": {"available": 60},
            "zll": {"available": 60},
            "zgp": {"available": 60}
        },
        "groups": {"available": 60},
        "scenes": {
            "available": 100,
            "lightstates": {"available": 1500}
        },
        "rules": {
            "available": 100,
            "lightstates": {
                "available": 1500
            },
        },
        "schedules": {"available": 100},
        "resourcelinks": {"available": 100},
        "whitelists": {"available": 100},
        "timezones": {
            "values": []
        },
        "streaming": {
            "available": streaming_available,
            "total": 10,
            "channels": 10
        }
    }
    return web.json_response(json_response)


@routes.route('*', '/{tail:.*}')
async def unknown_request(request):
    """Handle unknown requests (catch-all)."""
    if request.method in ["PUT", "POST"]:
        request_data = await request.json()
        _LOGGER.warning("Invalid request: %s --> %s", request, request_data)
    else:
        _LOGGER.warning("Invalid request: %s" % request)
    return web.Response(status=404)


async def __light_action(hass, entity, request_data):
    """Translate the Hue api request data to actions on a light entity."""

    # Construct what we need to send to the service
    domain = core.DOMAIN
    data = {ATTR_ENTITY_ID: entity.entity_id}

    power_on = request_data.get(STATE_ON, True)
    service = SERVICE_TURN_ON if power_on else SERVICE_TURN_OFF
    if power_on:

        # set the brightness, hue, saturation and color temp
        if HUE_API_ATTR_BRI in request_data:
            data[ATTR_BRIGHTNESS] = request_data[HUE_API_ATTR_BRI]

        if HUE_API_ATTR_HUE in request_data or HUE_API_ATTR_SAT in request_data:
            hue = request_data.get(HUE_API_ATTR_HUE, 0)
            sat = request_data.get(HUE_API_ATTR_SAT, 0)
            # Convert hs values to hass hs values
            hue = int((hue / HUE_API_ATTR_HUE_MAX) * 360)
            sat = int((sat / HUE_API_ATTR_SAT_MAX) * 100)
            data[ATTR_HS_COLOR] = (hue, sat)

        if HUE_API_ATTR_CT in request_data:
            data[ATTR_COLOR_TEMP] = request_data[HUE_API_ATTR_CT]

        if HUE_API_ATTR_XY in request_data:
            data[ATTR_XY_COLOR] = request_data[HUE_API_ATTR_XY]

        if HUE_API_ATTR_EFFECT in request_data:
            data[ATTR_EFFECT] = request_data[HUE_API_ATTR_EFFECT]

        if HUE_API_ATTR_ALERT in request_data:
            if request_data[HUE_API_ATTR_ALERT] == "select":
                data[ATTR_FLASH] = "short"
            elif request_data[HUE_API_ATTR_ALERT] == "lselect":
                data[ATTR_FLASH] = "long"

    if HUE_API_ATTR_TRANSITION in request_data:
        # Duration of the transition from the light to the new state
        # is given as a multiple of 100ms and defaults to 4 (400ms).
        transitiontime = request_data[HUE_API_ATTR_TRANSITION] / 100
        data[ATTR_TRANSITION] = transitiontime

    # execute service
    hass.async_create_task(hass.services.async_call(domain, service, data))


async def __get_entity_state(config, entity):
    """Retrieve and convert state and brightness values for an entity."""
    cached_state = config.cached_states.get(entity.entity_id, None)
    data = {
        STATE_ON: False,
        HUE_API_ATTR_BRI: None,
        HUE_API_ATTR_HUE: None,
        HUE_API_ATTR_SAT: None,
        HUE_API_ATTR_CT: None,
    }

    if cached_state is None:
        data[STATE_ON] = entity.state != STATE_OFF

        if data[STATE_ON]:
            data[HUE_API_ATTR_BRI] = entity.attributes.get(ATTR_BRIGHTNESS, 0)
            hue_sat = entity.attributes.get(ATTR_HS_COLOR, None)
            if hue_sat is not None:
                hue = hue_sat[0]
                sat = hue_sat[1]
                # Convert hass hs values back to hue hs values
                data[HUE_API_ATTR_HUE] = int(
                    (hue / 360.0) * HUE_API_ATTR_HUE_MAX)
                data[HUE_API_ATTR_SAT] = int(
                    (sat / 100.0) * HUE_API_ATTR_SAT_MAX)
            else:
                data[HUE_API_ATTR_HUE] = HUE_API_ATTR_HUE_MIN
                data[HUE_API_ATTR_SAT] = HUE_API_ATTR_SAT_MIN
            data[HUE_API_ATTR_CT] = entity.attributes.get(ATTR_COLOR_TEMP, 0)

        else:
            data[HUE_API_ATTR_BRI] = 0
            data[HUE_API_ATTR_HUE] = 0
            data[HUE_API_ATTR_SAT] = 0
            data[HUE_API_ATTR_CT] = 0

        # Get the entity's supported features
        entity_features = entity.attributes.get(ATTR_SUPPORTED_FEATURES, 0)

        if entity.domain == light.DOMAIN:
            if entity_features & SUPPORT_BRIGHTNESS:
                pass
    else:
        data = cached_state
        # Make sure brightness is valid
        if data[HUE_API_ATTR_BRI] is None:
            data[HUE_API_ATTR_BRI] = 255 if data[STATE_ON] else 0

        # Make sure hue/saturation are valid
        if (data[HUE_API_ATTR_HUE] is None) or (data[HUE_API_ATTR_SAT] is None):
            data[HUE_API_ATTR_HUE] = 0
            data[HUE_API_ATTR_SAT] = 0

        # If the light is off, set the color to off
        if data[HUE_API_ATTR_BRI] == 0:
            data[HUE_API_ATTR_HUE] = 0
            data[HUE_API_ATTR_SAT] = 0

    # Clamp brightness, hue, saturation, and color temp to valid values
    for (key, v_min, v_max) in (
        (HUE_API_ATTR_BRI, HUE_API_ATTR_BRI_MIN, HUE_API_ATTR_BRI_MAX),
        (HUE_API_ATTR_HUE, HUE_API_ATTR_HUE_MIN, HUE_API_ATTR_HUE_MAX),
        (HUE_API_ATTR_SAT, HUE_API_ATTR_SAT_MIN, HUE_API_ATTR_SAT_MAX),
        (HUE_API_ATTR_CT, HUE_API_ATTR_CT_MIN, HUE_API_ATTR_CT_MAX),
    ):
        if data[key] is not None:
            data[key] = max(v_min, min(data[key], v_max))

    return data


async def __entity_to_json(config, entity):
    """Convert an entity to its Hue bridge JSON representation."""
    entity_features = entity.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
    unique_id = hashlib.md5(entity.entity_id.encode()).hexdigest()
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
            HUE_API_ATTR_ON: entity.state == STATE_ON,
            "reachable": entity.state != STATE_UNAVAILABLE,
            "mode": "homeautomation",
        },
        "name": entity.name,
        "uniqueid": unique_id,
        "manufacturername": "Home Assistant",
        "productname": "Emulated Hue",
        "modelid": entity.entity_id,
        "swversion": "unknown",
    }

    # get device type, model etc. from the Hass device registry
    entity_attr = entity.attributes
    entity_reg = await config.hass.helpers.entity_registry.async_get_registry()
    device_reg = await config.hass.helpers.device_registry.async_get_registry()
    reg_entity = entity_reg.async_get(entity.entity_id)
    if reg_entity and reg_entity.device_id is not None:
        device = device_reg.async_get(reg_entity.device_id)
        if device:
            retval["manufacturername"] = device.manufacturer
            retval["modelid"] = device.model
            retval["productname"] = device.name
            if device.sw_version:
                retval["swversion"] = device.sw_version

    if ((entity_features & SUPPORT_BRIGHTNESS)
            and (entity_features & SUPPORT_COLOR)
            and (entity_features & SUPPORT_COLOR_TEMP)):
        # Extended Color light (Zigbee Device ID: 0x0210)
        # Same as Color light, but which supports additional setting of color temperature
        retval["type"] = "Extended color light"
        retval["state"].update(
            {
                HUE_API_ATTR_BRI: entity_attr.get(ATTR_BRIGHTNESS, 0),
                # TODO: remember last command to set colormode
                HUE_API_ATTR_COLORMODE: HUE_API_ATTR_XY,
                HUE_API_ATTR_XY: entity_attr.get(ATTR_XY_COLOR, [0, 0]),
                HUE_API_ATTR_CT: entity_attr.get(ATTR_COLOR_TEMP, 0),
                HUE_API_ATTR_EFFECT: entity_attr.get(ATTR_EFFECT, "none")
            }
        )
    elif (entity_features & SUPPORT_BRIGHTNESS) and (entity_features & SUPPORT_COLOR):
        # Color light (Zigbee Device ID: 0x0200)
        # Supports on/off, dimming and color control (hue/saturation, enhanced hue, color loop and XY)
        retval["type"] = "Color light"
        retval["state"].update(
            {
                HUE_API_ATTR_BRI: entity_attr.get(ATTR_BRIGHTNESS, 0),
                HUE_API_ATTR_COLORMODE: "xy",  # TODO: remember last command to set colormode
                HUE_API_ATTR_XY: entity_attr.get(ATTR_XY_COLOR, [0, 0]),
                HUE_API_ATTR_EFFECT: "none",
            }
        )
    elif (entity_features & SUPPORT_BRIGHTNESS) and (
        entity_features & SUPPORT_COLOR_TEMP
    ):
        # Color temperature light (Zigbee Device ID: 0x0220)
        # Supports groups, scenes, on/off, dimming, and setting of a color temperature
        retval["type"] = "Color temperature light"
        retval["state"].update({
            HUE_API_ATTR_COLORMODE: "ct",
            HUE_API_ATTR_CT: entity_attr.get(ATTR_COLOR_TEMP, 0)
        })
    elif entity_features & SUPPORT_BRIGHTNESS:
        # Dimmable light (Zigbee Device ID: 0x0100)
        # Supports groups, scenes, on/off and dimming
        brightness = entity_attr.get(ATTR_BRIGHTNESS, 0)
        retval["type"] = "Dimmable light"
        retval["state"].update({HUE_API_ATTR_BRI: brightness})
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


async def __create_hue_response(request_path, request_data):
    """Create success responses for all received keys."""
    request_path = request_path.replace(f"/api/{HUE_API_USERNAME}", "")
    json_response = []
    for key, val in request_data.items():
        obj_path = f"{request_path}/{key}"
        if "/groups" in obj_path:
            item = {"success": {"address": obj_path, "value": val}}
        else:
            item = {"success": {obj_path: val}}
        json_response.append(item)
    return json_response


async def __get_all_lights(request):
    """Create a list of all lights."""
    hass = request.app["hass"]
    config = request.app["config"]
    result = {}

    for entity_id in hass.states.async_entity_ids("light"):
        entity = hass.states.get(entity_id)
        light_id = await config.entity_id_to_light_id(entity_id)
        result[light_id] = await __entity_to_json(config, entity)

    return result


async def __get_local_items(config, itemtype="scenes"):
    """Get all items in storage of given type (scenes etc.)."""
    return await config.get_storage_value(itemtype, {})


async def __create_local_item(config, data, itemtype="scenes"):
    """Create item in storage of given type (scenes etc.)."""
    local_items = await config.get_storage_value(itemtype, {})
    # get first available id
    for i in range(1, 1000):
        item_id = str(i)
        if item_id not in local_items:
            break
    local_items[item_id] = data
    await config.set_storage_value(itemtype, local_items)
    return item_id


async def __get_all_groups(request):
    """Create a list of all groups."""
    hass = request.app["hass"]
    config = request.app["config"]
    result = {}

    # local groups first
    local_groups = await config.get_storage_value("groups", {})
    result.update(local_groups)

    # Hass areas/rooms
    hass = request.app["hass"]
    area_reg = await hass.helpers.area_registry.async_get_registry()

    for area in area_reg.areas.values():
        group_conf = result[area.id] = {
            "class": "Other",
            "type": "Room",
            "name": area.name,
            "lights": [],
            "sensors": [],
            "action": {
                "on": False
            },
            "state": {
                "any_on": False,
                "all_on": False
            }
        }
        lights_on = 0
        # get all entities for this device
        async for entity in __get_group_lights(config, area.id):
            entity = hass.states.get(entity.entity_id)
            light_id = await config.entity_id_to_light_id(entity.entity_id)
            group_conf["lights"].append(light_id)
            if entity.state == STATE_ON:
                lights_on += 1
                if lights_on == 1:
                    # set state of first light as group state
                    entity_obj = await __entity_to_json(config, entity)
                    group_conf["action"] = entity_obj["state"]
        if lights_on > 0:
            group_conf["state"]["any_on"] = True
        if lights_on == len(group_conf["lights"]):
            group_conf["state"]["all_on"] = True

    return result


async def __get_group_lights(config, group_id):
    """Get all light entities for a group"""
    hass = config.hass
    # try local groups first
    local_groups = await config.get_storage_value("groups", [])
    if group_id in local_groups:
        local_group = local_groups[group_id]
        for light_id in local_group["lights"]:
            entity = await config.entity_by_light_id(light_id)
            yield entity

    # fall back to hass groups (areas)
    else:
        device_reg = await hass.helpers.device_registry.async_get_registry()
        entity_reg = await hass.helpers.entity_registry.async_get_registry()
        for device in device_reg.devices.values():
            if device.area_id != group_id:
                continue
            # get all entities for this device
            for entity in entity_reg.entities.values():
                if entity.device_id != device.id or entity.disabled:
                    continue
                if entity.domain != "light":
                    continue
                entity = hass.states.get(entity.entity_id)
                yield entity


async def __get_bridge_config(request, full_details=False):
    """Return the (virtual) bridge configuration."""
    config = request.app["config"]
    result = {
        "bridgeid": config.bridge_id,
        "datastoreversion": "70",
        "factorynew": False,
        "ipaddress": config.advertise_ip,
        "linkbutton": False,
        "mac": config.mac_addr,
        "modelid": "BSB002",
        "name": "Home Assistant",
        "replacesbridgeid": None,
        "starterkitid": "",
        "swversion": "1935074050",
        "apiversion": "1.35.0"
    }
    if full_details:
        result.update({
            "Remote API enabled": False,
            "UTC": "2020-02-05T20:30:26",  # TODO
            "backup": {
                "errorcode": 0,
                "status": "idle"
            },
            "datastoreversion": "70",
            "dhcp": True,
            "internetservices": {
                "internet": "connected",
                "remoteaccess": "connected",
                "swupdate": "connected",
                "time": "connected"
            },
            "netmask": "255.255.255.0",
            "portalconnection": "connected",
            "portalservices": True,
            "portalstate": {
                "communication": "disconnected",
                "incoming": False,
                "outgoing": False,
                "signedon": True
            },
            "swupdate": {
                "checkforupdate": False,
                "devicetypes": {
                    "bridge": False,
                    "lights": [],
                    "sensors": []
                },
                "notify": True,
                "text": "",
                "updatestate": 0,
                "url": ""
            },
            "swupdate2": {
                "autoinstall": {
                    "on": True
                }
            },
            "timezone": "Europe/Amsterdam",
            "whitelist": {HUE_API_USERNAME: {"name": "HASS BRIDGE"}},
            "zigbeechannel": 25,
        })
    return result
