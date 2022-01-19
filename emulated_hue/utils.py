"""Emulated HUE Bridge for HomeAssistant - Helper utils."""
import asyncio
import inspect
import json
import logging
import os
import random
import socket
import string
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Union

import slugify as unicode_slug
from aiohttp import web

import emulated_hue.const as const

LOGGER = logging.getLogger(__name__)

# IP addresses of loopback interfaces
LOCAL_IPS = (ip_address("127.0.0.1"), ip_address("::1"))

# RFC1918 - Address allocation for Private Internets
LOCAL_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def is_local(address: Union[IPv4Address, IPv6Address]) -> bool:
    """Check if an address is local."""
    return address in LOCAL_IPS or any(address in network for network in LOCAL_NETWORKS)


# Taken from: http://stackoverflow.com/a/11735897
def get_local_ip() -> str:
    """Try to determine the local IP address of the machine."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Use Google Public DNS server to determine own IP
        sock.connect(("8.8.8.8", 80))

        return sock.getsockname()[0]  # type: ignore
    except socket.error:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return "127.0.0.1"
    finally:
        sock.close()


def get_ip_pton():
    """Return socket pton for local ip."""
    try:
        return socket.inet_pton(socket.AF_INET, get_local_ip())
    except OSError:
        return socket.inet_pton(socket.AF_INET6, get_local_ip())


def slugify(text: str) -> str:
    """Slugify a given text."""
    return unicode_slug.slugify(text, separator="_")  # type: ignore


def update_dict(dict1, dict2):
    """Helpermethod to update dict1 with values of dict2."""
    for key, value in dict2.items():
        if key in dict1 and isinstance(value, dict):
            update_dict(dict1[key], value)
        else:
            dict1[key] = value


def send_json_response(data) -> web.Response:
    """Send json response in unicode format instead of converting to ascii."""
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        content_type="application/json",
    )


# TODO: figure out correct response for:
# PUT: /api/username/lights/light_id
# {'config': {'startup': {'mode': 'safety'}}}
def send_success_response(
    request_path: str, request_data: dict, username: str = None
) -> web.Response:
    """Create success responses for all received keys."""
    if username:
        request_path = request_path.replace(f"/api/{username}", "")
    json_response = []
    for key, val in request_data.items():
        obj_path = f"{request_path}/{key}"
        item = {"success": {obj_path: val}}
        json_response.append(item)
    return send_json_response(json_response)


def send_error_response(address: str, description: str, type_num: int) -> web.Response:
    """Send error message using provided inputs with format of JSON with surrounding brackets."""
    address = address.replace("/api", "").split("//")[0]
    if address.startswith("/"):
        # strip out username
        address = "/" + "/".join(address.split("/")[2:])
    elif address == "":
        pass
    else:
        address = f"/{address}"
    description = description.format(path=address)
    response = [
        {"error": {"type": type_num, "address": address, "description": description}}
    ]
    return send_json_response(response)


def load_json(filename: str) -> dict:
    """Load JSON from file."""
    try:
        with open(filename, encoding="utf-8") as fdesc:
            return json.loads(fdesc.read())  # type: ignore
    except (FileNotFoundError, ValueError, OSError) as error:
        LOGGER.debug("Loading %s failed: %s", filename, error)
        return {}


async def async_save_json(filename: str, data: dict):
    """Save JSON data to a file."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, save_json, filename, data)


def save_json(filename: str, data: dict):
    """Save JSON data to a file."""
    safe_copy = filename + ".backup"
    if os.path.isfile(filename):
        os.replace(filename, safe_copy)
    try:
        json_data = json.dumps(data, sort_keys=True, indent=4, ensure_ascii=False)
        with open(filename, "w") as file_obj:
            file_obj.write(json_data)
    except IOError:
        LOGGER.exception("Failed to serialize to JSON: %s", filename)


def entity_attributes_to_int(attributes: dict):
    """Convert entity attribute floats to int."""
    for attr_name, attr_data in attributes.items():
        if attr_name == "xy_color":
            continue
        if isinstance(attr_data, float):
            attributes[attr_name] = int(attr_data)
        elif isinstance(attr_data, list):
            for i, value in enumerate(attr_data):
                if isinstance(value, float):
                    attr_data[i] = int(value)
    return attributes


def create_secure_string(length: int, hex_compatible: bool = False) -> str:
    """Create secure random string for username, client key, and tokens."""
    if hex_compatible:
        character_array = string.hexdigits
    else:
        character_array = string.ascii_letters + string.digits + "-"
    return "".join(random.SystemRandom().choice(character_array) for _ in range(length))


def convert_color_mode(color_mode: str, initial_type: str) -> str:
    """Convert color_mode names from initial_type to other type for xy, hs, and ct."""
    if initial_type == const.HASS:
        hass_color_modes = {
            const.HASS_COLOR_MODE_COLOR_TEMP: const.HUE_ATTR_CT,
            const.HASS_COLOR_MODE_XY: const.HUE_ATTR_XY,
            const.HASS_COLOR_MODE_HS: const.HUE_ATTR_HS,
        }
        return hass_color_modes.get(color_mode, "xy")
    else:
        hue_color_modes = {
            const.HUE_ATTR_CT: const.HASS_COLOR_MODE_COLOR_TEMP,
            const.HUE_ATTR_XY: const.HASS_COLOR_MODE_XY,
            const.HUE_ATTR_HS: const.HASS_COLOR_MODE_HS,
            const.HUE_ATTR_HUE: const.HASS_COLOR_MODE_HS,
            const.HUE_ATTR_SAT: const.HASS_COLOR_MODE_HS,
        }
        return hue_color_modes.get(color_mode, "xy")


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

    def add_manual_route(self, method: str, path: str, handler, **kwargs) -> None:
        """Add manual route handler."""
        super().route(method, path, **kwargs)(handler)

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
