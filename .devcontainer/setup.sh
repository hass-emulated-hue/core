#!/bin/bash

pip3 install --no-cache-dir -r requirements.txt
pip3 install --no-cache-dir -r requirements-dev.txt
pre-commit install --install-hooks
