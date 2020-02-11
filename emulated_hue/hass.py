"""Emulated HUE Bridge for HomeAssistant - Connection to hass."""
import asyncio
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)


class HomeAssistant:
    """Connection to HomeAssistant (over websockets)."""

    def __init__(self, hue):
        """Initialize class."""
        self.hue = hue
        self._states = {}
        self.__send_ws = None
        self.__last_id = 10
        self._callbacks = {}
        self.device_registry = {}
        self.entity_registry = {}
        self.area_registry = {}
        url = self.hue.config.hass_url
        if url.startswith("https://"):
            self._use_ssl = True
            self._host = url.replace("https://", "")
        else:
            self._use_ssl = False
            self._host = url.replace("http://", "")
        self.http_session = None

    @property
    def states(self):
        """Return all hass states."""
        return self._states

    async def async_setup(self):
        """Perform async setup."""
        self.http_session = aiohttp.ClientSession(
            loop=self.hue.event_loop, connector=aiohttp.TCPConnector()
        )
        self.hue.event_loop.create_task(self.__hass_websocket())

    async def get_state(self, entity_id, attribute=None):
        """Get state(obj) of a hass entity."""
        state_obj = self._states.get(entity_id, None)
        if not state_obj:
            # fallback to rest api
            state_obj = await self.__get_data("states/%s" % entity_id)
            self._states[entity_id] = state_obj
        if state_obj:
            if attribute == "state":
                return state_obj["state"]
            elif attribute:
                return state_obj["attributes"].get(attribute)
            else:
                return state_obj
        return None

    async def lights(self):
        """Get all light entities."""
        return await self.items_by_domain("light")

    async def items_by_domain(self, domain):
        """Retrieve all items for a domain."""
        all_items = []
        for key, value in self._states.items():
            if key.startswith(domain):
                all_items.append(value)
        return all_items

    async def call_service(self, domain, service, service_data=None):
        """Call service on hass."""
        if not self.__send_ws:
            return False
        msg = {"type": "call_service", "domain": domain, "service": service}
        if service_data:
            msg["service_data"] = service_data
        return await self.__send_ws(msg)

    async def __set_state(self, entity_id, new_state, state_attributes=None):
        """Set state to hass entity."""
        if state_attributes is None:
            state_attributes = {}
        data = {
            "state": new_state,
            "entity_id": entity_id,
            "attributes": state_attributes,
        }
        return await self.__post_data("states/%s" % entity_id, data)

    async def __hass_websocket(self):
        """Receive events from Hass through websockets."""
        protocol = "wss" if self._use_ssl else "ws"
        while self.hue.event_loop.is_running():
            try:
                self.__last_id = 10
                self._callbacks = {}
                async with self.http_session.ws_connect(
                    "%s://%s/api/websocket" % (protocol, self._host), verify_ssl=False
                ) as conn:

                    async def send_msg(msg, callback=None):
                        """Callback: send message to the websockets client."""
                        msg_id = self.__last_id + 1
                        self.__last_id = msg_id
                        msg["id"] = msg_id
                        if callback:
                            self._callbacks[msg_id] = callback
                        await conn.send_json(msg)

                    async for msg in conn:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if msg.data == "close cmd":
                                await conn.close()
                                break
                            else:
                                data = msg.json()
                                if data["type"] == "auth_required":
                                    # send auth token
                                    auth_msg = {
                                        "type": "auth",
                                        "access_token": self.hue.config.hass_token,
                                    }
                                    await conn.send_json(auth_msg)
                                elif data["type"] == "auth_invalid":
                                    raise Exception(data)
                                elif data["type"] == "auth_ok":
                                    # register callback
                                    self.__send_ws = send_msg
                                    # subscribe to events
                                    await send_msg(
                                        {
                                            "type": "subscribe_events",
                                            "event_type": "state_changed",
                                        },
                                        callback=self.__state_changed,
                                    )
                                    # request all current states
                                    await send_msg(
                                        {"type": "get_states"},
                                        callback=self.__all_states,
                                    )
                                    # request all area, device and entity registry
                                    await send_msg(
                                        {"type": "config/area_registry/list"},
                                        callback=self.__receive_area_registry,
                                    )
                                    await send_msg(
                                        {"type": "config/device_registry/list"},
                                        callback=self.__receive_device_registry,
                                    )
                                    await send_msg(
                                        {"type": "config/entity_registry/list"},
                                        callback=self.__receive_entity_registry,
                                    )
                                elif data["id"] in self._callbacks:
                                    asyncio.create_task(
                                        self._callbacks[data["id"]](data)
                                    )
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise Exception("error in websocket")
            except asyncio.CancelledError:
                raise asyncio.CancelledError()
            except (
                aiohttp.client_exceptions.ClientConnectorError,
                ConnectionRefusedError,
            ) as exc:
                _LOGGER.error(exc)
                await asyncio.sleep(10)

    async def __state_changed(self, msg):
        """Received state_changed event."""
        if "event" not in msg:
            return
        event_type = msg["event"]["event_type"]
        event_data = msg["event"]["data"]
        if event_type == "state_changed":
            entity_id = event_data["entity_id"]
            self._states[entity_id] = event_data["new_state"]
        else:
            _LOGGER.debug(event_type)

    async def __all_states(self, msg):
        """Received all states."""
        _LOGGER.debug("Got all states")
        for item in msg["result"]:
            entity_id = item["entity_id"]
            self._states[entity_id] = item

    async def __receive_area_registry(self, msg):
        """Received area registry."""
        _LOGGER.debug("Received area registry.")
        for item in msg["result"]:
            item_id = item["area_id"]
            self.area_registry[item_id] = item

    async def __receive_device_registry(self, msg):
        """Received device registry."""
        _LOGGER.debug("Received device registry.")
        for item in msg["result"]:
            item_id = item["id"]
            self.device_registry[item_id] = item

    async def __receive_entity_registry(self, msg):
        """Received entity registry."""
        _LOGGER.debug("Received entity registry.")
        for item in msg["result"]:
            item_id = item["entity_id"]
            self.entity_registry[item_id] = item

    async def __get_data(self, endpoint):
        """Get data from hass rest api."""
        url = "http://%s/api/%s" % (self._host, endpoint)
        if self._use_ssl:
            url = "https://%s/api/%s" % (self._host, endpoint)
        headers = {
            "Authorization": f"Bearer {self.hue.config.hass_token}",
            "Content-Type": "application/json",
        }
        async with self.http_session.get(
            url, headers=headers, verify_ssl=False
        ) as response:
            return await response.json()

    async def __post_data(self, endpoint, data):
        """Post data to hass rest api."""
        url = "http://%s/api/%s" % (self._host, endpoint)
        if self._use_ssl:
            url = "https://%s/api/%s" % (self._host, endpoint)
        headers = {
            "Authorization": "Bearer %s" % self.hue.config.hass_token,
            "Content-Type": "application/json",
        }
        async with self.http_session.post(
            url, headers=headers, json=data, verify_ssl=False
        ) as response:
            return await response.json()
