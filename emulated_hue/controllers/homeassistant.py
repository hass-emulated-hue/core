"""Controller for Home Assistant communication."""
from hass_client import HomeAssistantClient

from emulated_hue.const import (
    HASS_ATTR_ENTITY_ID,
    HASS_DOMAIN_HOMEASSISTANT,
    HASS_DOMAIN_PERSISTENT_NOTIFICATION,
    HASS_SERVICE_PERSISTENT_NOTIFICATION_CREATE,
    HASS_SERVICE_PERSISTENT_NOTIFICATION_DISMISS,
    HASS_SERVICE_TURN_OFF,
    HASS_SERVICE_TURN_ON,
)


class HomeAssistantController:
    """Controller for Home Assistant communication class."""

    def __init__(self, hass: HomeAssistantClient):
        """Initialize the Home Assistant controller."""
        self._hass = hass

    async def async_turn_off(self, entity_id: str, data: dict) -> None:
        """
        Turn off a generic entity in Home Assistant.

            :param entity_id: The ID of the entity.
            :param data: The service data.
        """
        data[HASS_ATTR_ENTITY_ID] = entity_id
        await self._hass.call_service(
            HASS_DOMAIN_HOMEASSISTANT, HASS_SERVICE_TURN_OFF, data
        )

    async def async_turn_on(self, entity_id: str, data: dict) -> None:
        """
        Turn on a generic entity in Home Assistant.

            :param entity_id: The ID of the entity.
            :param data: The service data.
        """
        data[HASS_ATTR_ENTITY_ID] = entity_id
        await self._hass.call_service(
            HASS_DOMAIN_HOMEASSISTANT, HASS_SERVICE_TURN_ON, data
        )

    async def async_get_area_devices(
        self, area_id: str, domain_filter: list = None
    ) -> list:
        """
        Get the enabled devices in a Home Assistant area matching a domain filter.

            :param area_id: The Home Assistant area ID.
            :param domain_filter: A list of domains to filter the devices by.
            :return: A list of devices in the area.
        """
        domain_filter = domain_filter if domain_filter else ["light."]
        area_entities = []
        for entity in self._hass.entity_registry.values():
            if entity["disabled_by"]:
                # do not include disabled devices
                continue
            # only include devices that are matched by the filter
            if domain_filter and not any(
                entity["entity_id"].startswith(domain) for domain in domain_filter
            ):
                continue
            device = self._hass.device_registry.get(entity["device_id"])
            # check if entity or device attached to entity is in area
            if entity["area_id"] == area_id or (
                device and device["area_id"] == area_id
            ):
                area_entities.append(entity)
        return area_entities

    async def async_get_entity_state(self, entity_id: str) -> dict:
        """
        Get the state of an entity in Home Assistant.

            :param entity_id: The ID of the entity.
        """
        return self._hass.get_state(entity_id, attribute=None)

    async def async_create_notification(
        self,
        msg: str,
        notification_id: str,
        title: str = "Emulated Hue Bridge",
    ) -> None:
        """
        Create a notification in Home Assistant.

            :param msg: The message to display in the notification.
            :param notification_id: The ID of the notification.
            :param title: The title of the notification.
        """
        await self._hass.call_service(
            HASS_DOMAIN_PERSISTENT_NOTIFICATION,
            HASS_SERVICE_PERSISTENT_NOTIFICATION_CREATE,
            {
                "notification_id": notification_id,
                "title": title,
                "message": msg,
            },
        )

    async def async_dismiss_notification(self, notification_id: str) -> None:
        """
        Dismisses a notification in Home Assistant.

            :param notification_id: The ID of the notification.
        """
        await self._hass.call_service(
            HASS_DOMAIN_PERSISTENT_NOTIFICATION,
            HASS_SERVICE_PERSISTENT_NOTIFICATION_DISMISS,
            {"notification_id": notification_id},
        )
