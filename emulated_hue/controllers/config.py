"""Hold configuration variables for the emulated hue bridge."""
import asyncio
import datetime
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from getmac import get_mac_address

from emulated_hue.const import CONFIG_WRITE_DELAY_SECONDS, DEFAULT_THROTTLE_MS
from emulated_hue.utils import (
    async_save_json,
    create_secure_string,
    get_local_ip,
    load_json,
)

from .devices import force_update_all
from .entertainment import EntertainmentAPI
from .models import Controller

LOGGER = logging.getLogger(__name__)

CONFIG_FILE = "emulated_hue.json"
DEFINITIONS_FILE = os.path.join(
    os.path.dirname(Path(__file__).parent.absolute()), "definitions.json"
)


class Config:
    """Hold configuration variables for the emulated hue bridge."""

    def __init__(
        self,
        ctl: Controller,
        data_path: str,
        http_port: int,
        https_port: int,
        use_default_ports: bool,
    ):
        """Initialize the instance."""
        self.ctl = ctl
        self.data_path = data_path
        if not os.path.isdir(data_path):
            os.mkdir(data_path)
        self._config = load_json(self.get_path(CONFIG_FILE))
        self._definitions = load_json(DEFINITIONS_FILE)
        self._link_mode_enabled = False
        self._link_mode_discovery_key = None

        # Get the IP address that will be passed to during discovery
        self._ip_addr = get_local_ip()
        LOGGER.info("Auto detected listen IP address is %s", self.ip_addr)

        # Get the ports that the Hue bridge will listen on
        # ports can be overridden but Hue apps expect ports 80/443
        # so this is only usefull when running a reverse proxy on the same host
        self.http_port = http_port
        self.https_port = https_port
        self.use_default_ports = use_default_ports
        if http_port != 80 or https_port != 443:
            LOGGER.warning(
                "Non default http/https ports detected. "
                "Hue apps require the bridge at the default ports 80/443, use at your own risk."
            )
            if self.use_default_ports:
                LOGGER.warning(
                    "Using default HTTP port for discovery with non default HTTP/S ports. "
                    "Are you using a reverse proxy?"
                )

        mac_addr = str(get_mac_address(ip=self.ip_addr))
        if not mac_addr or len(mac_addr) < 16:
            # try again without ip
            mac_addr = str(get_mac_address())
        if not mac_addr or len(mac_addr) < 16:
            # fall back to dummy mac
            mac_addr = "b6:82:d3:45:ac:29"
        self._mac_addr = mac_addr
        mac_str = mac_addr.replace(":", "")
        self._bridge_id = (mac_str[:6] + "FFFE" + mac_str[6:]).upper()
        self._bridge_serial = mac_str.lower()
        self._bridge_uid = f"2f402f80-da50-11e1-9b23-{mac_str}"

        self._saver_task: asyncio.Task | None = None

        self._entertainment_api: EntertainmentAPI | None = None

    async def create_save_task(self) -> None:
        """Create a task to save the config."""
        if self._saver_task is None or self._saver_task.done():
            self._saver_task = asyncio.create_task(self._commit_config())

    async def _commit_config(self, immediate_commit: bool = False) -> None:
        if not immediate_commit:
            await asyncio.sleep(CONFIG_WRITE_DELAY_SECONDS)
        await async_save_json(self.get_path(CONFIG_FILE), self._config)

    async def async_stop(self) -> None:
        """Save the config on shutdown."""
        self.stop_entertainment()
        if self._saver_task is not None and not self._saver_task.done():
            self._saver_task.cancel()
            await self._commit_config(immediate_commit=True)

    @property
    def ip_addr(self) -> str:
        """Return ip address of the emulated bridge."""
        return self._ip_addr

    @property
    def mac_addr(self) -> str:
        """Return mac address of the emulated bridge."""
        return self._mac_addr

    @property
    def bridge_id(self) -> str:
        """Return the bridge id of the emulated bridge."""
        return self._bridge_id

    @property
    def bridge_serial(self) -> str:
        """Return the bridge serial of the emulated bridge."""
        return self._bridge_serial

    @property
    def bridge_uid(self) -> str:
        """Return the bridge UID of the emulated bridge."""
        return self._bridge_uid

    @property
    def link_mode_enabled(self) -> bool:
        """Return state of link mode."""
        return self._link_mode_enabled

    @property
    def link_mode_discovery_key(self) -> str | None:
        """Return the temporary token which enables linking."""
        return self._link_mode_discovery_key

    @property
    def bridge_name(self) -> str:
        """Return the friendly name for the emulated bridge."""
        return self.get_storage_value("bridge_config", "name", "Hass Emulated Hue")

    @property
    def definitions(self) -> dict:
        """Return the definitions dictionary (e.g. bridge sw version)."""
        # TODO: Periodically check for updates of the definitions file on Github ?
        return self._definitions

    @property
    def entertainment_active(self) -> bool:
        """Return current state of entertainment mode."""
        return self._entertainment_api is not None

    def get_path(self, filename: str) -> str:
        """Get path to file at data location."""
        return os.path.join(self.data_path, filename)

    async def async_entity_id_to_light_id(self, entity_id: str) -> str:
        """Get a unique light_id number for the hass entity id."""
        lights = await self.async_get_storage_value("lights", default={})
        for key, value in lights.items():
            if entity_id == value["entity_id"]:
                return key
        # light does not yet exist in config, create default config
        next_light_id = "1"
        if lights:
            next_light_id = str(max(int(k) for k in lights) + 1)
        # generate unique id (fake zigbee address) from entity id
        unique_id = hashlib.md5(entity_id.encode()).hexdigest()
        unique_id = "00:{}:{}:{}:{}:{}:{}:{}-{}".format(
            unique_id[0:2],
            unique_id[2:4],
            unique_id[4:6],
            unique_id[6:8],
            unique_id[8:10],
            unique_id[10:12],
            unique_id[12:14],
            unique_id[14:16],
        )
        # create default light config
        light_config = {
            "entity_id": entity_id,
            "enabled": True,
            "name": "",
            "uniqueid": unique_id,
            # TODO: detect type of light from hass device config ?
            "config": {
                "archetype": "sultanbulb",
                "function": "mixed",
                "direction": "omnidirectional",
                # TODO: find some way to control the actual startup state?
                "startup": {"configured": True, "mode": "safety"},
            },
            "throttle": DEFAULT_THROTTLE_MS,
        }
        await self.async_set_storage_value("lights", next_light_id, light_config)
        return next_light_id

    async def async_get_light_config(self, light_id: str) -> dict:
        """Return light config for given light id."""
        conf = await self.async_get_storage_value("lights", light_id)
        if not conf:
            raise Exception(f"Light {light_id} not found!")
        return conf

    async def async_entity_id_from_light_id(self, light_id: str) -> str:
        """Return the hass entity by supplying a light id."""
        light_config = await self.async_get_light_config(light_id)
        if not light_config:
            raise Exception("Invalid light_id provided!")
        entity_id = light_config["entity_id"]
        entities = self.ctl.controller_hass.get_entities()
        if entity_id not in entities:
            raise Exception(f"Entity {entity_id} not found!")
        return entity_id

    async def async_area_id_to_group_id(self, area_id: str) -> str:
        """Get a unique group_id number for the hass area_id."""
        groups = await self.async_get_storage_value("groups", default={})
        for key, value in groups.items():
            if area_id == value.get("area_id"):
                return key
        # group does not yet exist in config, create default config
        next_group_id = "1"
        if groups:
            next_group_id = str(max(int(k) for k in groups) + 1)
        group_config = {
            "area_id": area_id,
            "enabled": True,
            "name": "",
            "class": "Other",
            "type": "Room",
            "lights": [],
            "sensors": [],
            "action": {"on": False},
            "state": {"any_on": False, "all_on": False},
        }
        await self.async_set_storage_value("groups", next_group_id, group_config)
        return next_group_id

    async def async_get_group_config(self, group_id: str) -> dict:
        """Return group config for given group id."""
        conf = await self.async_get_storage_value("groups", group_id)
        if not conf:
            raise Exception(f"Group {group_id} not found!")
        return conf

    async def async_get_storage_value(
        self, key: str, subkey: str = None, default: Any | None = None
    ) -> Any:
        """Get a value from persistent storage."""
        return self.get_storage_value(key, subkey, default)

    def get_storage_value(
        self, key: str, subkey: str = None, default: Any | None = None
    ) -> Any:
        """Get a value from persistent storage."""
        main_val = self._config.get(key, None)
        if main_val is None:
            return default
        if subkey:
            return main_val.get(subkey, default)
        return main_val

    async def async_set_storage_value(
        self, key: str, subkey: str, value: str or dict
    ) -> None:
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
            await self.create_save_task()

    async def async_delete_storage_value(self, key: str, subkey: str = None) -> None:
        """Delete a value in persistent storage."""
        # if Home Assistant group/area, we just disable it
        if key == "groups" and subkey:
            # when deleting groups, we must delete all associated scenes
            scenes = await self.async_get_storage_value("scenes", default={})
            for scene_num, scene_data in scenes.copy().items():
                if scene_data["group"] == subkey:
                    await self.async_delete_storage_value("scenes", scene_num)
            # simply disable the group if its a HASS group
            group_conf = await self.async_get_group_config(subkey)
            if group_conf["class"] == "Home Assistant":
                # group_conf = {**group_conf}
                group_conf["enabled"] = False
                return await self.async_set_storage_value("groups", subkey, group_conf)
        # if Home Assistant light, we just disable it
        if key == "lights" and subkey:
            light_conf = await self.async_get_light_config(subkey)
            # light_conf = {**light_conf}
            light_conf["enabled"] = False
            return await self.async_set_storage_value("lights", subkey, light_conf)
        # all other local storage items
        if subkey:
            self._config[key].pop(subkey, None)
        else:
            self._config.pop(key)
        await async_save_json(self.get_path(CONFIG_FILE), self._config)
        return None

    async def async_get_users(self) -> dict:
        """Get all registered users as dict."""
        return await self.async_get_storage_value("users", default={})

    async def async_get_user(self, username: str) -> dict:
        """Get details for given username."""
        user_data = await self.async_get_storage_value("users", username)
        if user_data:
            user_data["last use date"] = (
                datetime.datetime.now().isoformat().split(".")[0]
            )
            await self.async_set_storage_value("users", username, user_data)
        return user_data

    async def async_create_user(self, devicetype: str) -> dict:
        """Create a new user for the api access."""
        if not self._link_mode_enabled:
            raise Exception("Link mode not enabled!")
        all_users = await self.async_get_users()
        # devicetype is used as deviceid: <application_name>#<devicename>
        # return existing user if already registered
        for item in all_users.values():
            if item["name"] == devicetype:
                return item
        # create username and clientkey
        username = create_secure_string(40)
        clientkey = create_secure_string(32, True).upper()
        user_obj = {
            "name": devicetype,
            "clientkey": clientkey,
            "create date": datetime.datetime.now().isoformat().split(".")[0],
            "username": username,
        }
        await self.async_set_storage_value("users", username, user_obj)
        return user_obj

    async def delete_user(self, username: str) -> None:
        """Delete a user."""
        await self.async_delete_storage_value("users", username)

    async def async_enable_link_mode(self) -> None:
        """Enable link mode for the duration of 5 minutes."""
        if self._link_mode_enabled:
            return  # already enabled
        self._link_mode_enabled = True

        def auto_disable():
            self.ctl.loop.create_task(self.async_disable_link_mode())

        self.ctl.loop.call_later(300, auto_disable)
        LOGGER.info("Link mode is enabled for the next 5 minutes.")

    async def async_disable_link_mode(self) -> None:
        """Disable link mode on the virtual bridge."""
        self._link_mode_enabled = False
        LOGGER.info("Link mode is disabled.")

    async def async_enable_link_mode_discovery(self) -> None:
        """Enable link mode discovery (notification) for the duration of 5 minutes."""

        if self._link_mode_discovery_key:
            return  # already active

        LOGGER.info(
            "Link request detected - Use the Homeassistant frontend to confirm this link request."
        )

        self._link_mode_discovery_key = create_secure_string(32)
        # create persistent notification in hass
        # user can click the link in the notification to enable linking

        url = f"http://{self.ip_addr}/link/{self._link_mode_discovery_key}"
        msg = "Click the link below to enable pairing mode on the virtual bridge:\n\n"
        msg += f"**[Enable link mode]({url})**"

        await self.ctl.controller_hass.async_create_notification(
            msg, "hue_bridge_link_requested"
        )

        # make sure that the notification and link request are dismissed after 5 minutes

        def auto_disable():
            self.ctl.loop.create_task(self.async_disable_link_mode_discovery())

        self.ctl.loop.call_later(300, auto_disable)

    async def async_disable_link_mode_discovery(self) -> None:
        """Disable link mode discovery (remove notification in hass)."""
        self._link_mode_discovery_key = None
        await self.ctl.controller_hass.async_dismiss_notification(
            "hue_bridge_link_requested"
        )

    def start_entertainment(self, group_conf: dict, user_data: dict) -> bool:
        """Start the entertainment mode server."""
        if not self._entertainment_api:
            self._entertainment_api = EntertainmentAPI(self.ctl, group_conf, user_data)
            return True
        return False

    def stop_entertainment(self) -> None:
        """Stop the entertainment mode server if it is active."""
        if self._entertainment_api:
            self._entertainment_api.stop()
            self._entertainment_api = None
        # force update of all light states
        self.ctl.loop.create_task(force_update_all())
