"""Hold configuration variables for the emulated hue bridge."""
import datetime
import logging
import os
import uuid

from getmac import get_mac_address

from .utils import get_local_ip, load_json, save_json

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE = "emulated_hue.json"


class Config:
    """Hold configuration variables for the emulated hue bridge."""

    def __init__(self, hue, data_path, hass_url, hass_token):
        """Initialize the instance."""
        self.hue = hue
        self.hass_url = hass_url
        self.hass_token = hass_token
        self.data_path = data_path
        self._config = load_json(self.get_path(CONFIG_FILE))
        self._link_mode_enabled = False
        self._link_mode_discovery_key = None

        # Get the IP address that will be passed to during discovery
        self.host_ip_addr = get_local_ip()
        _LOGGER.info(
            "Listen IP address not specified, auto-detected address is %s",
            self.host_ip_addr,
        )

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
        self.mac_str = mac_addr.replace(":", "")
        self.bridge_id = (self.mac_str[:6] + "FFFE" + self.mac_str[6:]).upper()
        self.bridge_uid = f"2f402f80-da50-11e1-9b23-{self.mac_str}"

    @property
    def link_mode_enabled(self):
        """Return state of link mode."""
        return self._link_mode_enabled

    @property
    def link_mode_discovery_key(self):
        """Return the temporary token which enables linking."""
        return self._link_mode_discovery_key

    def get_path(self, filename):
        """Get path to file at data location."""
        return os.path.join(self.data_path, filename)

    async def entity_id_to_light_id(self, entity_id):
        """Get a unique light_id number for the hass entity id."""
        numbers = await self.get_storage_value("light_ids")
        for number, ent_id in numbers.items():
            if entity_id == ent_id:
                return number
        number = "1"
        if numbers:
            number = str(max(int(k) for k in numbers) + 1)
        await self.set_storage_value("light_ids", number, entity_id)
        return number

    async def light_id_to_entity_id(self, number):
        """Convert unique light_id number to entity id."""
        return await self.get_storage_value("light_ids", number)

    async def entity_by_light_id(self, light_id):
        """Return the hass entity by supplying a light id."""
        entity_id = await self.light_id_to_entity_id(light_id)
        if not entity_id:
            raise Exception("Invalid light_id provided!")
        entity = await self.hue.hass.get_state(entity_id)
        if not entity:
            raise Exception(f"Entity {entity_id} not found!")
        return entity

    async def get_storage_value(self, key, subkey=None):
        """Get a value from persistent storage."""
        main_val = self._config.get(key, None)
        if main_val is None:
            return {}
        if subkey:
            return main_val.get(subkey, None)
        return main_val

    async def set_storage_value(self, key, subkey, value):
        """Set a value in persistent storage."""
        needs_save = False
        if subkey is None and self._config.get(key) != value:
            # main key changed
            self._config[key] = value
            needs_save = True
        elif subkey and key not in self._config:
            # new sublevel created
            self._config[key] = {subkey: value}
            needs_save = True
        elif subkey and self._config[key].get(key) != value:
            # sub key changed
            self._config[key][subkey] = value
            needs_save = True
        # save config to file if changed
        if needs_save:
            save_json(self.get_path(CONFIG_FILE), self._config)

    async def delete_storage_value(self, key, subkey=None):
        """Delete a value in persistent storage."""
        if subkey:
            self._config[key].pop(subkey, None)
        else:
            self._config.pop(key)
        save_json(self.get_path(CONFIG_FILE), self._config)

    async def get_users(self):
        """Get all registered users as dict."""
        return await self.get_storage_value("users")

    async def get_user(self, username):
        """Get details for given username."""
        return await self.get_storage_value("users", username)

    async def create_user(self, devicetype):
        """Create a new user for the api access."""
        if not self._link_mode_enabled:
            raise Exception("Link mode not enabled!")
        all_users = await self.get_users()
        # devicetype is used as deviceid: <application_name>#<devicename>
        # return existing user if already registered
        for item in all_users.values():
            if item["name"] == devicetype:
                return item
        # create username and clientkey with uuid module
        username = str(uuid.uuid4()).replace("-", "")[:20]
        clientkey = str(uuid.uuid4()).replace("-", "")
        user_obj = {
            "name": devicetype,
            "clientkey": clientkey,
            "create date": datetime.datetime.now().strftime("%Y-%M-%DT%H:%M:%S"),
            "username": username,
        }
        await self.set_storage_value("users", username, user_obj)
        return user_obj

    async def delete_user(self, username):
        """Delete a user."""
        await self.delete_storage_value("users", username)

    async def enable_link_mode(self):
        """Enable link mode for the duration of 30 seconds."""
        if self._link_mode_enabled:
            return  # already enabled
        self._link_mode_enabled = True

        def auto_disable():
            self.hue.event_loop.create_task(self.disable_link_mode())

        self.hue.event_loop.call_later(60, auto_disable)
        _LOGGER.info("Link mode is enabled for the next 60 seconds.")

    async def disable_link_mode(self):
        """Disable link mode on the virtual bridge."""
        self._link_mode_enabled = False
        _LOGGER.info("Link mode is disabled.")

    async def enable_link_mode_discovery(self):
        """Enable link mode discovery for the duration of 120 seconds."""
        if self._link_mode_discovery_key:
            return  # already active

        self._link_mode_discovery_key = str(uuid.uuid4())
        # create persistent notification in hass
        # user can click the link in the notification to enable linking

        url = f"http://{self.host_ip_addr}/link?token={self._link_mode_discovery_key}"
        msg = "Click the link below to enable pairing mode on the virtual bridge:\n\n"
        msg += f"**[Enable link mode]({url})**"
        msg_details = {
            "notification_id": "hue_bridge_link_requested",
            "title": "Emulated HUE Bridge",
            "message": msg,
        }
        await self.hue.hass.call_service(
            "persistent_notification", "create", msg_details
        )
        _LOGGER.info(
            "Link request detected - Use the Homeassistant frontend to confirm this link request."
        )
        # make sure that the notification and link request are dismissed after 90 seconds

        def auto_disable():
            self._link_mode_discovery_key = None
            self.hue.event_loop.create_task(
                self.hue.hass.call_service(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": "hue_bridge_link_requested"},
                )
            )

        self.hue.event_loop.call_later(120, auto_disable)
