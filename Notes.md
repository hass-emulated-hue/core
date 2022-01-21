# Todo/Random notes

Code block to get esphome node IPs:
```python
    related = await self._hass.send_command({"type": "search/related", "item_type": "entity", "item_id": "light.light_1"})
    entries = await self._hass.rest_get_data("/config/esphome/entries")
    esphome_entries = {}
    for entry in entries:
        entry_id = entry.get("entry_id")
        host = entry.get("host")
        if entry_id and host:
            esphome_entries[entry_id] = host
    ip = esphome_entries.get(related.get("config_entry")[0])
    LOGGER.info("IP: %s", ip)
```

Verify entity is esphome using `/api/config/config_entries/entry`
