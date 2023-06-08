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

import slugify as unicode_slug
from aiohttp import web

from emulated_hue import const

LOGGER = logging.getLogger(__name__)

# IP addresses of loopback interfaces
LOCAL_IPS = (ip_address("127.0.0.1"), ip_address("::1"))

# RFC1918 - Address allocation for Private Internets
LOCAL_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def wrap_number(value: float, start_value: float, max_value: float) -> float:
    """Wrap a number between start and end value."""
    return (value - start_value) % (max_value - start_value) + start_value


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Clamp a value between a min and max value."""
    return min(max(value, min_value), max_value)


def is_local(address: IPv4Address | IPv6Address) -> bool:
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
    except OSError:
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
        headers={
            "server": "nginx",
            "Access-Control-Max-Age": "3600",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, HEAD",
            "Access-Control-Allow-Headers": "Content-Type",
            "X-XSS-Protection": "1; mode=block",
            "X-Frame-Options": "SAMEORIGIN",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "no-referrer",
        },
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
    if address == "":
        pass
    else:
        if "//" in address:
            address = address.replace("/api/", "")
        else:
            address = address.lstrip("/").split("/")
            address = f"/{address[2]}" if len(address) > 2 else "/"
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
    except OSError:
        LOGGER.exception("Failed to serialize to JSON: %s", filename)


def create_secure_string(length: int, hex_compatible: bool = False) -> str:
    """Create secure random string for username, client key, and tokens."""
    if hex_compatible:
        character_array = string.hexdigits
    else:
        character_array = string.ascii_letters + string.digits + "-"
    return "".join(random.SystemRandom().choice(character_array) for _ in range(length))


def convert_flash_state(state: str, initial_type: str) -> str:
    """Convert flash state between hass and hue."""
    flash_states = {
        "select": "short",
        "lselect": "long",
    }
    for hue_state, hass_state in flash_states.items():
        if initial_type == const.HASS:
            if state == hass_state:
                return hue_state
        else:
            if state == hue_state:
                return hass_state
    return state


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
        return f"<ClassRouteTableDef count={len(self._items)}>"

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
