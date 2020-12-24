"""Hold configuration variables for the emulated hue bridge."""
import datetime
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Optional

from getmac import get_mac_address

from .utils import get_local_ip, load_json, save_json

if TYPE_CHECKING:
    from emulated_hue import HueEmulator
else:
    HueEmulator = "HueEmulator"


LOGGER = logging.getLogger(__name__)

CONFIG_FILE = "emulated_hue.json"
DEFINITIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "definitions.json"
)


class Config:
    """Hold configuration variables for the emulated hue bridge."""

    def __init__(self, hue: HueEmulator, data_path: str):
        """Initialize the instance."""
        self.hue = hue
        self.data_path = data_path
        if not os.path.isdir(data_path):
            os.mkdir(data_path)
        self._config = load_json(self.get_path(CONFIG_FILE))
        self._definitions = load_json(DEFINITIONS_FILE)
        self._link_mode_enabled = False
        self._link_mode_discovery_key = None

        # Get the IP address that will be passed to during discovery
        self.host_ip_addr = get_local_ip()
        LOGGER.info("Auto detected listen IP address is %s", self.host_ip_addr)

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
    def link_mode_enabled(self) -> bool:
        """Return state of link mode."""
        return self._link_mode_enabled

    @property
    def link_mode_discovery_key(self) -> Optional[str]:
        """Return the temporary token which enables linking."""
        return self._link_mode_discovery_key

    @property
    def definitions(self) -> dict:
        """Return the definitions dictionary (e.g. bridge sw version)."""
        # TODO: Periodically check for updates of the definitions file on Github ?
        return self._definitions

    def get_path(self, filename: str) -> str:
        """Get path to file at data location."""
        return os.path.join(self.data_path, filename)

    async def async_entity_id_to_light_id(self, entity_id: str) -> str:
        """Get a unique light_id number for the hass entity id."""
        numbers = await self.async_get_storage_value("light_ids")
        for number, ent_id in numbers.items():
            if entity_id == ent_id:
                return number
        number = "1"
        if numbers:
            number = str(max(int(k) for k in numbers) + 1)
        await self.async_set_storage_value("light_ids", number, entity_id)
        return number

    async def async_light_id_to_entity_id(self, number: str) -> str:
        """Convert unique light_id number to entity id."""
        return await self.async_get_storage_value("light_ids", number)

    async def async_entity_by_light_id(self, light_id: str) -> str:
        """Return the hass entity by supplying a light id."""
        entity_id = await self.async_light_id_to_entity_id(light_id)
        if not entity_id:
            raise Exception("Invalid light_id provided!")
        entity = self.hue.hass.get_state(entity_id, attribute=None)
        if not entity:
            raise Exception(f"Entity {entity_id} not found!")
        return entity

    async def async_get_storage_value(self, key: str, subkey: str = None) -> Any:
        """Get a value from persistent storage."""
        main_val = self._config.get(key, None)
        if main_val is None:
            return {}
        if subkey:
            return main_val.get(subkey, None)
        return main_val

    async def async_set_storage_value(self, key: str, subkey: str, value: str) -> None:
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

    async def async_delete_storage_value(self, key: str, subkey: str = None) -> None:
        """Delete a value in persistent storage."""
        if subkey:
            self._config[key].pop(subkey, None)
        else:
            self._config.pop(key)
        save_json(self.get_path(CONFIG_FILE), self._config)

    async def get_users(self) -> dict:
        """Get all registered users as dict."""
        return await self.async_get_storage_value("users")

    async def async_get_user(self, username: str) -> dict:
        """Get details for given username."""
        return await self.async_get_storage_value("users", username)

    async def async_create_user(self, devicetype: str) -> dict:
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
        await self.async_set_storage_value("users", username, user_obj)
        return user_obj

    async def delete_user(self, username: str) -> None:
        """Delete a user."""
        await self.async_delete_storage_value("users", username)

    async def async_enable_link_mode(self) -> None:
        """Enable link mode for the duration of 60 seconds."""
        if self._link_mode_enabled:
            return  # already enabled
        self._link_mode_enabled = True

        def auto_disable():
            self.hue.loop.create_task(self.disable_link_mode())

        self.hue.loop.call_later(60, auto_disable)
        LOGGER.info("Link mode is enabled for the next 60 seconds.")

    async def disable_link_mode(self) -> None:
        """Disable link mode on the virtual bridge."""
        self._link_mode_enabled = False
        LOGGER.info("Link mode is disabled.")

    async def async_enable_link_mode_discovery(self) -> None:
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
        await self.hue.hass.async_call_service(
            "persistent_notification", "create", msg_details
        )
        LOGGER.info(
            "Link request detected - Use the Homeassistant frontend to confirm this link request."
        )
        # make sure that the notification and link request are dismissed after 120 seconds

        def auto_disable():
            self._link_mode_discovery_key = None
            self.hue.loop.create_task(
                self.hue.hass.async_call_service(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": "hue_bridge_link_requested"},
                )
            )

        self.hue.loop.call_later(120, auto_disable)
