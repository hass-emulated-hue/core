"""Controller for Home Assistant communication."""
import logging
from collections.abc import Awaitable, Callable

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

LOGGER = logging.getLogger(__name__)


class HomeAssistantController(HomeAssistantClient):
    """Abstraction on hass client API."""

    async def async_turn_off(self, entity_id: str) -> None:
        """
        Turn off a generic entity in Home Assistant.

            :param entity_id: The ID of the entity.
            :param data: The service data.
        """
        data = {HASS_ATTR_ENTITY_ID: entity_id}
        await self.call_service(HASS_DOMAIN_HOMEASSISTANT, HASS_SERVICE_TURN_OFF, data)

    async def async_turn_on(self, entity_id: str, data: dict) -> None:
        """
        Turn on a generic entity in Home Assistant.

            :param entity_id: The ID of the entity.
            :param data: The service data.
        """
        data[HASS_ATTR_ENTITY_ID] = entity_id
        await self.call_service(HASS_DOMAIN_HOMEASSISTANT, HASS_SERVICE_TURN_ON, data)

    def get_entity_state(self, entity_id: str) -> dict:
        """
        Get the state of an entity in Home Assistant.

            :param entity_id: The ID of the entity.
        """
        return self.get_state(entity_id, attribute=None)

    def get_device_attributes(self, device_id: str) -> dict:
        """Get the attributes of a device in Home Assistant."""
        return self.device_registry.get(device_id)

    def get_device_id_from_entity_id(self, entity_id: str) -> str | None:
        """Get the device ID from an entity ID."""
        return self.entity_registry.get(entity_id, {}).get("device_id")

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
        await self.call_service(
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
        await self.call_service(
            HASS_DOMAIN_PERSISTENT_NOTIFICATION,
            HASS_SERVICE_PERSISTENT_NOTIFICATION_DISMISS,
            {"notification_id": notification_id},
        )

    def register_state_changed_callback(
        self, callback: Callable[..., Awaitable[None]], entity_id: str
    ) -> Callable:
        """
        Register callback to notify of state change event on an entity.

            :param callback: The callback to call when the state changes.
            :param entity_id: The ID of the entity.
            :return: A callable to remove the callback.
        """
        return self.register_event_callback(
            callback, event_filter="state_changed", entity_filter=entity_id
        )

    def get_entities(self, domain: str = "light") -> list[str]:
        """
        Get entity_ids of a domain in Home Assistant.

            :param domain: The domain of the entities.
            :return: A list of entity IDs.
        """
        return [
            entity["entity_id"] for entity in self.items_by_domain(domain) if entity
        ]

    async def async_get_area_entities(
        self, domain_filter: list | None = None
    ) -> dict[str, dict]:
        """
        Get all areas mapped to entities contained. Excludes disabled entities.

            :return: A dictionary of devices in the area. {area_id: {name: str, entities:[entity_ids]}}
        """
        domain_filter = domain_filter if domain_filter else ["light."]
        result = self.area_registry.copy()
        for area_id in result:
            area_entities = []
            for entity in self.entity_registry.values():
                if entity["disabled_by"]:
                    # do not include disabled devices
                    continue
                # only include devices that are matched by the filter
                if domain_filter and not any(
                    entity["entity_id"].startswith(domain) for domain in domain_filter
                ):
                    continue
                device = self.device_registry.get(entity["device_id"])
                # check if entity or device attached to entity is in area
                if entity["area_id"] == area_id or (
                    device and device["area_id"] == area_id
                ):
                    area_entities.append(entity["entity_id"])
            result[area_id]["entities"] = area_entities
        return result
