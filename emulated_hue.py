from emulated_hue import HueEmulator
import logging
import asyncio
import sys
from aiorun import run
import argparse
import os

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
    # auto detect hassio
    if os.path.isfile('/data/options.json') and os.environ.get('HASSIO_TOKEN'):
        token = os.environ['HASSIO_TOKEN']
        datapath = "/data"
        url = 'http://hassio/homeassistant'
    else:
        args = parser.parse_args()
        datapath = args.data
        url = args.url
        token = args.token

    hue = HueEmulator(event_loop, datapath, url, token)
    run(hue.start(), loop=event_loop)