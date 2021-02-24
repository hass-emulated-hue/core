"""Emulated Hue quick start."""
import argparse
import logging
import os

from aiorun import run
from emulated_hue import HueEmulator

IS_SUPERVISOR = os.path.isfile("/data/options.json") and os.environ.get("HASSIO_TOKEN")

# pylint: disable=invalid-name
if __name__ == "__main__":

    logger = logging.getLogger()
    logformat = logging.Formatter(
        "%(asctime)-15s %(levelname)-5s %(name)s -- %(message)s"
    )
    consolehandler = logging.StreamHandler()
    consolehandler.setFormatter(logformat)
    logger.addHandler(consolehandler)
    logger.setLevel(logging.INFO)

    if IS_SUPERVISOR:
        default_data_dir = "/config/hass-emulated-hue"
    else:
        default_data_dir = (
            os.getenv("APPDATA") if os.name == "nt" else os.path.expanduser("~")
        )
        default_data_dir = os.path.join(default_data_dir, ".emulated_hue")

    parser = argparse.ArgumentParser(description="Home Assistant HUE Emulation.")

    parser.add_argument(
        "--data",
        type=str,
        help="path to store config files",
        default=os.getenv("DATA_DIR", default_data_dir),
    )
    parser.add_argument(
        "--url",
        type=str,
        help="url to HomeAssistant",
        default=os.getenv("HASS_URL", "http://hassio/homeassistant"),
    )
    parser.add_argument(
        "--token",
        type=str,
        help="Long Lived Token for HomeAssistant",
        default=os.getenv("HASS_TOKEN", os.getenv("HASSIO_TOKEN")),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable more verbose logging"
    )
    parser.add_argument(
        "--http-port",
        type=int,
        help="Port to run the HTTP server (for use with reverse proxy, use with care)",
        default=os.getenv("HTTP_PORT", 80),
    )
    parser.add_argument(
        "--https-port",
        type=int,
        help="Port to run the HTTPS server (for use with reverse proxy, use with care)",
        default=os.getenv("HTTPS_PORT", 443),
    )

    args = parser.parse_args()
    datapath = args.data
    url = args.url
    token = args.token
    if args.verbose or os.getenv("VERBOSE", "").strip() == "true":
        logger.setLevel(logging.DEBUG)
    # turn down logging for hass-client
    logging.getLogger("hass_client").setLevel(logging.INFO)

    hue = HueEmulator(datapath, url, token, args.http_port, args.https_port)

    def on_shutdown(loop):
        """Call on loop shutdown."""
        loop.run_until_complete(hue.async_stop())

    if os.name != "nt":
        run(hue.async_start(), use_uvloop=True, shutdown_callback=on_shutdown)
    else:
        run(hue.async_start(), use_uvloop=False, shutdown_callback=on_shutdown)
