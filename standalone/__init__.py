"""Support for local control of entities by emulating a Philips Hue bridge."""
import sys
import os
import logging
import asyncio

from .upnp import UPNPResponderThread
from .config import Config
from .hue_api import HueApi
from .hass import HomeAssistant
from .hue_entertainment import EntertainmentThread


_LOGGER = logging.getLogger(__name__)

class HueEmulator():

    def __init__(self, event_loop, data_path, hass_url, hass_token):
        ''' 
            Create an instance of HueEmulator
            :param data_path: file location to store the data
            :param event_loop: asyncio event_loop
            :param hass_url: full url to HomeAssistant (e.g. http://hass:8123)
            :param hass_token: Long Lived Token for HomeAssistant
        '''
        self.event_loop = event_loop
        self.config = Config(self, data_path, hass_url, hass_token)
        self.hass = HomeAssistant(self)
        self.hue_api = HueApi(self)
        self.upnp_listener = UPNPResponderThread(self.config)

    async def start(self):
        '''Start running the Hue emulation.'''
        await self.hass.async_setup()
        await self.hue_api.async_setup()
        self.upnp_listener.start()
        # wait for exit
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            _LOGGER.info("Application shutdown")
            self.upnp_listener.stop()
            await self.hue_api.stop()
            
