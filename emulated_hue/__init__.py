"""Support for local control of entities by emulating a Philips Hue bridge."""
import logging
import os

from aiohttp import web
import ssl
import voluptuous as vol
from getmac import get_mac_address

from homeassistant import util
from homeassistant.components.http import real_ip
from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.deprecation import get_deprecated
from homeassistant.util.json import load_json, save_json

from .hue_api import routes

from .create_cert import generate_selfsigned_cert
from .upnp import UPNPResponderThread

DOMAIN = "emulated_hue"

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE = ".storage/emulated_hue.config"

CONF_ADVERTISE_IP = "advertise_ip"
CONF_ADVERTISE_PORT = "advertise_port"
CONF_ENTITIES = "entities"
CONF_ENTITY_HIDDEN = "hidden"
CONF_ENTITY_NAME = "name"
CONF_EXPOSE_BY_DEFAULT = "expose_by_default"
CONF_EXPOSED_DOMAINS = "exposed_domains"
CONF_HOST_IP = "host_ip"
CONF_http_port = "http_port"
CONF_OFF_MAPS_TO_ON_DOMAINS = "off_maps_to_on_domains"
CONF_TYPE = "type"
CONF_UPNP_BIND_MULTICAST = "upnp_bind_multicast"

# ports are hardcoded as Hue apps expect these ports to be default
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTPS_PORT = 443
DEFAULT_UPNP_BIND_MULTICAST = True


CONFIG_ENTITY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTITY_NAME): cv.string,
        vol.Optional(CONF_ENTITY_HIDDEN): cv.boolean,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_HOST_IP): cv.string,
                vol.Optional(CONF_ADVERTISE_IP): cv.string,
                vol.Optional(CONF_ADVERTISE_PORT): cv.port,
                vol.Optional(CONF_UPNP_BIND_MULTICAST): cv.boolean
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

ATTR_EMULATED_HUE = "emulated_hue"
ATTR_EMULATED_HUE_NAME = "emulated_hue_name"
ATTR_EMULATED_HUE_HIDDEN = "emulated_hue_hidden"


async def async_setup(hass, yaml_config):
    """Activate the emulated_hue component."""
    config = Config(hass, yaml_config.get(DOMAIN, {}))

    app = web.Application()
    app["hass"] = hass
    app["config"] = config
    app["entertainment"] = None
    real_ip.setup_real_ip(app, False, [])
    # We misunderstood the startup signal. You're not allowed to change
    # anything during startup. Temp workaround.
    # pylint: disable=protected-access
    app._on_startup.freeze()
    await app.startup()

    runner = None
    http_site = None
    https_site = None

    upnp_listener = UPNPResponderThread(
        config.host_ip_addr,
        config.http_port,
        config.upnp_bind_multicast,
        config.advertise_ip,
        config.advertise_port,
    )

    async def stop_emulated_hue_bridge(event):
        """Stop the emulated hue bridge."""
        upnp_listener.stop()
        if app["entertainment"]:
            app["entertainment"].stop()
        if http_site:
            await http_site.stop()
        if https_site:
            await https_site.stop()
        if runner:
            await runner.cleanup()

    async def start_emulated_hue_bridge(event):
        """Start the emulated hue bridge."""
        upnp_listener.start()
        nonlocal http_site
        nonlocal https_site
        nonlocal runner

        app.add_routes(routes)

        runner = web.AppRunner(app)
        await runner.setup()

        
        mac_addr = str(get_mac_address(ip=config.host_ip_addr))
        if not mac_addr or len(mac_addr) < 16:
            # fall back to dummy mac
            mac_addr = "b6:82:d3:45:ac:29"
        config.mac_addr = mac_addr
        config.mac_str = mac_addr.replace(':','')
        config.bridge_id = (config.mac_str[:6] + 'FFFE' + config.mac_str[6:]).upper()
        config.bridge_uid = f'2f402f80-da50-11e1-9b23-{config.mac_str}'

        cert_file = hass.config.path('.storage/emulated_hue_cert.pem')
        key_file = hass.config.path('.storage/emulated_hue_cert_key.pem')
        if not os.path.isfile(cert_file) or not os.path.isfile(key_file):
            generate_selfsigned_cert(cert_file, key_file, config)
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)
        http_site = web.TCPSite(runner, config.host_ip_addr, config.http_port)
        https_site = web.TCPSite(runner, config.host_ip_addr, config.https_port,
                                ssl_context=ssl_context)
        try:
            await http_site.start()
        except OSError as error:
            _LOGGER.error(
                "Failed to create HTTP server at port %d: %s", config.http_port, error)
        try:
            await https_site.start()
        except OSError as error:
            _LOGGER.error(
                "Failed to create HTTPS server at port %d: %s", config.https_port, error)

        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, stop_emulated_hue_bridge
        )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_emulated_hue_bridge)

    return True

class Config:
    """Hold configuration variables for the emulated hue bridge."""

    def __init__(self, hass, conf):
        """Initialize the instance."""
        self.hass = hass
        self.cached_states = {}
        self._storage = None

        # Get the IP address that will be passed to during discovery
        self.host_ip_addr = conf.get(CONF_HOST_IP)
        if self.host_ip_addr is None:
            self.host_ip_addr = util.get_local_ip()
            _LOGGER.info(
                "Listen IP address not specified, auto-detected address is %s",
                self.host_ip_addr)

        # Get the ports that the Hue bridge will listen on
        self.http_port = DEFAULT_HTTP_PORT
        self.https_port = DEFAULT_HTTPS_PORT

        # Get whether or not UPNP binds to multicast address (239.255.255.250)
        # or to the unicast address (host_ip_addr)
        self.upnp_bind_multicast = conf.get(
            CONF_UPNP_BIND_MULTICAST, DEFAULT_UPNP_BIND_MULTICAST)

        # Calculated effective advertised IP and port for network isolation
        self.advertise_ip = conf.get(CONF_ADVERTISE_IP) or self.host_ip_addr
        self.advertise_port = conf.get(CONF_ADVERTISE_PORT) or self.http_port

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
        entity = self.hass.states.get(entity_id)
        if not entity:
            raise Exception(f"Entity {entity_id} not found!")
        return entity

    async def get_storage_value(self, key, def_value=None):
        """Get a value from persistent storage."""
        if self._storage is None:
            self._storage = _load_json(self.hass.config.path(CONFIG_FILE))
        return self._storage.get(key, def_value)

    async def set_storage_value(self, key, value):
        """Set a value in persistent storage."""
        self._storage[key] = value
        save_json(self.hass.config.path(CONFIG_FILE), self._storage)


def _load_json(filename):
    """Load JSON, handling invalid syntax."""
    try:
        return load_json(filename)
    except HomeAssistantError:
        pass
    return {}
