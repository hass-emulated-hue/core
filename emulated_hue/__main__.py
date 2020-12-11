#!/usr/bin/env python3
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

    default_data_dir = (
        os.getenv("APPDATA") if os.name == "nt" else os.path.expanduser("~")
    )
    default_data_dir = os.path.join(default_data_dir, ".emulated_hue")

    parser = argparse.ArgumentParser(description="Home Assistant HUE Emulation.")
    if not IS_SUPERVISOR:
        parser.add_argument(
            "--data",
            type=str,
            help="path to store config files",
            default=default_data_dir,
        )
        parser.add_argument(
            "--url", type=str, help="url to HomeAssistant", required=True
        )
        parser.add_argument(
            "--token",
            type=str,
            help="Long Lived Token for HomeAssistant",
            required=True,
        )
    parser.add_argument(
        "--verbose", type=bool, help="Enable more verbose logging", default=False
    )

    # auto detect hassio
    if IS_SUPERVISOR:
        token = os.environ["HASSIO_TOKEN"]
        datapath = "/data"
        url = "http://hassio/homeassistant"
    else:
        args = parser.parse_args()
        datapath = args.data
        url = args.url
        token = args.token
        if args.verbose:
            logger.setLevel(logging.DEBUG)

    hue = HueEmulator(datapath, url, token)
    run(hue.start(), use_uvloop=True)
