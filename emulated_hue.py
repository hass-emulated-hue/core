from emulated_hue import HueEmulator
import logging
import asyncio
import sys
from aiorun import run
import argparse

if __name__ == "__main__":

    logger = logging.getLogger()
    logformat = logging.Formatter('%(asctime)-15s %(levelname)-5s %(name)s.%(module)s -- %(message)s')
    consolehandler = logging.StreamHandler()
    consolehandler.setFormatter(logformat)
    logger.addHandler(consolehandler)
    logger.setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser(description='Home Assistant HUE Emulation.')
    parser.add_argument('--data', type=str, help='path to store config files', required=True)
    parser.add_argument('--url', type=str, help='url to HomeAssistant', required=True)
    parser.add_argument('--token', type=str, help='Long Lived Token for HomeAssistant', required=True)

    # create event_loop with uvloop
    event_loop = asyncio.get_event_loop()
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        # uvloop is not available on Windows so safe to ignore this
        logger.warning("uvloop support is disabled")
    args = parser.parse_args()
    hue = HueEmulator(event_loop, args.data, args.url, args.token)
    run(hue.start(), loop=event_loop)