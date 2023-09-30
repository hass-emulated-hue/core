import logging

from aiohttp import web
from emulated_hue.controllers import Controller
from emulated_hue.utils import send_error_response

LOGGER = logging.getLogger(__name__)


class HueApiEndpoints:
    """Base class for Hue API endpoints."""

    def __init__(self, ctl: Controller):
        """Initialize the v1 api."""
        self.ctl = ctl

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
