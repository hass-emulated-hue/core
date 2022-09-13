"""Support for a Hue API to control Home Assistant."""
import logging
import os
import ssl
from typing import TYPE_CHECKING

from aiohttp import web

from emulated_hue.apiv1 import HueApiV1Endpoints
from emulated_hue.controllers import Controller
from emulated_hue.ssl_cert import async_generate_selfsigned_cert, check_certificate

if TYPE_CHECKING:
    from emulated_hue import HueEmulator
else:
    HueEmulator = "HueEmulator"

LOGGER = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_static")


class HueWeb:
    """Support for a Hue API to control Home Assistant."""

    runner = None

    def __init__(self, ctl: Controller):
        """Initialize with Hue object."""
        self.ctl: Controller = ctl
        self.v1_api = HueApiV1Endpoints(ctl)
        self.http_site: web.TCPSite | None = None
        self.https_site: web.TCPSite | None = None

    async def async_setup(self):
        """Async set-up of the webserver."""
        app = web.Application()
        # add all routes defined with decorator
        app.add_routes(self.v1_api.route)
        # static files hosting
        app.router.add_static("/", STATIC_DIR, append_version=True)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()

        # Create and start the HTTP webserver/api
        self.http_site = web.TCPSite(
            self.runner, port=self.ctl.config_instance.http_port
        )
        try:
            await self.http_site.start()
            LOGGER.info(
                "Started HTTP webserver on port %s", self.ctl.config_instance.http_port
            )
        except OSError as error:
            LOGGER.error(
                "Failed to create HTTP server at port %d: %s",
                self.ctl.config_instance.http_port,
                error,
            )

        # create self signed certificate for HTTPS API
        cert_file = self.ctl.config_instance.get_path("cert.pem")
        key_file = self.ctl.config_instance.get_path("cert_key.pem")
        if not check_certificate(cert_file, self.ctl.config_instance):
            await async_generate_selfsigned_cert(
                cert_file, key_file, self.ctl.config_instance
            )
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)

        # Create and start the HTTPS webserver/API
        self.https_site = web.TCPSite(
            self.runner,
            port=self.ctl.config_instance.https_port,
            ssl_context=ssl_context,
        )
        try:
            await self.https_site.start()
            LOGGER.info(
                "Started HTTPS webserver on port %s",
                self.ctl.config_instance.https_port,
            )
        except OSError as error:
            LOGGER.error(
                "Failed to create HTTPS server at port %d: %s",
                self.ctl.config_instance.https_port,
                error,
            )

    async def async_stop(self):
        """Stop the webserver."""
        await self.http_site.stop()
        await self.https_site.stop()
        await self.v1_api.async_stop()
