FROM python:3.10-buster AS dev_base

## Install requirements
RUN apt update \
    && apt install --no-install-recommends -y \
    curl \
    tzdata \
    ca-certificates \
    openssl \
    sudo

#############

# PyCharm #

#############

FROM dev_base AS dev_pycharm

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install pydevd-pycharm
