"""Common model info for Light models."""


LST002 = {
    "config": {
        "archetype": "huelightstrip",
        "function": "mixed",
        "direction": "omnidirectional",
    },
    "capabilities": {
        "certified": True,
        "control": {
            "mindimlevel": 40,
            "maxlumen": 1600,
            "colorgamuttype": "C",
            "colorgamut": [[0.6915, 0.3083], [0.17, 0.7], [0.1532, 0.0475]],
            "ct": {"min": 153, "max": 500},
        },
        "streaming": {"renderer": True, "proxy": True},
    },
    "swversion": "5.127.1.26581",
}


ESPRESSIF_ESP_WROVER_KIT = {
    "config": {
        "archetype": "huelightstrip",
        "function": "mixed",
        "direction": "omnidirectional",
    },
    "capabilities": {
        "certified": True,
        "control": {
            "mindimlevel": 40,
            "maxlumen": 1600,
            "colorgamuttype": "C",
            "colorgamut": [[0.6915, 0.3083], [0.17, 0.7], [0.1532, 0.0475]],
            "ct": {"min": 153, "max": 500},
        },
        "streaming": {"renderer": True, "proxy": True},
    },
    "swversion": "5.127.1.26581",
}
