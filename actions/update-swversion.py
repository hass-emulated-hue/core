"""Ran daily to automatically obtain and commit latest swversion."""

import json
import logging
import os
import re

import requests

logger = logging.getLogger()
logformat = logging.Formatter("%(asctime)-15s %(levelname)-5s %(name)s -- %(message)s")
consolehandler = logging.StreamHandler()
consolehandler.setFormatter(logformat)
logger.addHandler(consolehandler)
logger.setLevel(logging.INFO)
LOGGER = logging.getLogger(__name__)


def load_json(filename: str) -> dict:
    """Load JSON from file."""
    try:
        with open(filename, encoding="utf-8") as fdesc:
            return json.loads(fdesc.read())  # type: ignore
    except (FileNotFoundError, ValueError, OSError) as error:
        LOGGER.debug("Loading %s failed: %s", filename, error)
        return {}


def save_json(filename: str, data: dict, backup: bool = True):
    """Save JSON data to a file."""
    if backup:
        safe_copy = filename + ".backup"
        if os.path.isfile(filename):
            os.replace(filename, safe_copy)
    try:
        json_data = json.dumps(data, sort_keys=False, indent=2, ensure_ascii=False)
        with open(filename, "w") as file_obj:
            file_obj.write(json_data)
    except IOError:
        LOGGER.exception("Failed to serialize to JSON: %s", filename)


def get_latest_version() -> int:
    """Scrape latest Hue version from website."""

    def extract_version(line) -> int:
        match = re.search(r"(firmware)(.+)([0-9]+)(.+)(bridge v2)", line)
        if match:
            partial = match.group(2) + match.group(3)
            match = re.search(r"([0-9]+)", partial).group()
            if match:
                return int(match)

    url = "https://www.philips-hue.com/en-us/support/release-notes/bridge"
    response = requests.get(url)
    webpage_lines = [
        x.lower() for x in response.content.decode("utf-8").splitlines() if x
    ]
    versions = list(filter(None.__ne__, map(extract_version, webpage_lines)))
    # assume versions are in listed in order from newest to oldest. Next best alternative to saving all dates
    return versions[0]


DEFINITIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../emulated_hue/definitions.json"
)
definitions = load_json(DEFINITIONS_FILE)

latest_version = str(get_latest_version())

current_version = definitions["bridge"]["basic"]["swversion"]
LOGGER.info(f"Current version: {current_version}, Latest version: {latest_version}")

if current_version != latest_version:
    LOGGER.info(
        f"Current version is not equal to latest version! Committing latest version: {latest_version}"
    )
    definitions["bridge"]["basic"]["swversion"] = latest_version
    save_json(DEFINITIONS_FILE, definitions, False)
    # Use failure code as need to commit
    exit(1)
else:
    LOGGER.info(f"Current version is equal to latest version. Exiting...")
    # Success == No need to commit
    exit(0)
