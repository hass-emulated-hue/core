"""Hold configuration variables for the emulated hue bridge."""
from getmac import get_mac_address
from .ssl_cert import generate_selfsigned_cert
import logging
import os

from .utils import get_local_ip, load_json, save_json

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE = "config.json"

class Config:
    """Hold configuration variables for the emulated hue bridge."""

    def __init__(self, hue, data_path, hass_url, hass_token):
        """Initialize the instance."""
        self.hue = hue
        self.hass_url = hass_url
        self.hass_token = hass_token
        self.data_path = data_path
        self._config = None
        
        # Get the IP address that will be passed to during discovery
        self.host_ip_addr = get_local_ip()
        _LOGGER.info(
            "Listen IP address not specified, auto-detected address is %s",
            self.host_ip_addr)

        # Get the ports that the Hue bridge will listen on
        # ports are currently hardcoded as Hue apps expect these ports
        self.http_port = 80
        self.https_port = 443

        # Get whether or not UPNP binds to multicast address (239.255.255.250)
        # or to the unicast address (host_ip_addr)
        self.upnp_bind_multicast = True

        mac_addr = str(get_mac_address(ip=self.host_ip_addr))
        if not mac_addr or len(mac_addr) < 16:
            # fall back to dummy mac
            mac_addr = "b6:82:d3:45:ac:29"
        self.mac_addr = mac_addr
        self.mac_str = mac_addr.replace(':','')
        self.bridge_id = (self.mac_str[:6] + 'FFFE' + self.mac_str[6:]).upper()
        self.bridge_uid = f'2f402f80-da50-11e1-9b23-{self.mac_str}'

    def get_path(self, filename):
        """Get path to file at data location."""
        return os.path.join(self.data_path, filename)

    async def entity_id_to_light_id(self, entity_id):
        """Get a unique light_id number for the hass entity id."""
        numbers = await self.get_storage_value("light_ids", {})
        for number, ent_id in numbers.items():
            if entity_id == ent_id:
                return number
        number = "1"
        if numbers:
            number = str(max(int(k) for k in numbers) + 1)
        numbers[number] = entity_id
        await self.set_storage_value("light_ids", numbers)
        return number

    async def light_id_to_entity_id(self, number):
        """Convert unique light_id number to entity id."""
        numbers = await self.get_storage_value("light_ids")
        return numbers.get(number)

    async def entity_by_light_id(self, light_id):
        """Return the hass entity by supplying a light id."""
        entity_id = await self.light_id_to_entity_id(light_id)
        if not entity_id:
            raise Exception("Invalid light_id provided!")
        entity = await self.hue.hass.get_state(entity_id)
        if not entity:
            raise Exception(f"Entity {entity_id} not found!")
        return entity

    async def get_storage_value(self, key, def_value=None):
        """Get a value from persistent storage."""
        if self._config is None:
            self._config = load_json(self.get_path(CONFIG_FILE))
        return self._config.get(key, def_value)

    async def set_storage_value(self, key, value):
        """Set a value in persistent storage."""
        self._config[key] = value
        save_json(self.get_path(CONFIG_FILE), self._config)


