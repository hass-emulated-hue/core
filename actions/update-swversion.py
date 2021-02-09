import os
import re

import requests

import sys
sys.path.append('..')
from emulated_hue.utils import load_json, save_json

DEFINITIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../emulated_hue/definitions.json"
)
definitions = load_json(DEFINITIONS_FILE)

def get_latest_version() -> int:
    def extract_version(line) -> int:
        if match := re.search(r'(firmware)(.+)([0-9]+)(.+)(bridge v2)', line):
            partial = match.group(2) + match.group(3)
            if match := re.search(r'([0-9]+)', partial).group():
                return int(match)

    url = 'https://www.philips-hue.com/en-us/support/release-notes/bridge'
    response = requests.get(url)
    webpage_lines = [x.lower() for x in response.content.decode('utf-8').splitlines() if x]
    versions = list(filter(None.__ne__, map(extract_version, webpage_lines)))
    # assume versions are in listed in order from newest to oldest. Next best alternative to saving all dates
    return versions[0]


latest_version = str(get_latest_version())

current_version = definitions["bridge"]["basic"]["swversion"]

if current_version != latest_version:
    definitions["bridge"]["basic"]["swversion"] = latest_version
    save_json(DEFINITIONS_FILE, definitions, False)
    print("true")
else:
    print("false")
