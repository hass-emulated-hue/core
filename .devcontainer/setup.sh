#!/bin/bash

pip3 install --no-cache-dir -r requirements.txt
pip3 install --no-cache-dir -r .devcontainer/requirements-dev.txt
pre-commit install
