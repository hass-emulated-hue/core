FROM python:3.8-slim-buster AS dev_base

COPY requirements.txt ./

## Install requirements
RUN apt update \
    && apt install --no-install-recommends -y \
        curl \
        tzdata \
        ca-certificates \
        openssl

RUN pip3 install --no-cache-dir -r requirements.txt

#############

# VSCODE #

#############
FROM dev_base AS dev_vscode

COPY ./.devcontainer/requirements-vscode.txt ./

RUN pip3 install --no-cache-dir -r requirements-vscode.txt

#############

# PyCharm #

#############

FROM dev_base AS dev_pycharm

RUN pip3 install pydevd-pycharm~=202.7660.27
