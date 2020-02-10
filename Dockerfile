ARG BUILD_FROM=hassioaddons/base-python:latest
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Copy Python requirements file
COPY requirements.txt /tmp/

RUN \
    apk add --no-cache --virtual .build-dependencies \
        build-base=0.5-r1 \
        cmake=3.15.5-r0 \
        libuv-dev=1.34.0-r0 \
        openssl-dev=1.1.1d-r3 \
        libffi-dev \
        python3-dev \
    && apk add --no-cache \
        openssl=1.1.1d-r3 \
    && pip3 install \
        --no-cache-dir \
        -r /tmp/requirements.txt \
    && apk del --no-cache --purge .build-dependencies \
    && find /usr/local \
        \( -type d -a -name test -o -name tests -o -name '__pycache__' \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' + \
    && rm -f -r \
        /root/.cache \
        /root/.cmake \
        /tmp/*

# Copy app
COPY /emulated_hue /usr/local/app/emulated_hue
COPY emulated_hue.py /usr/local/app/

# Default volume (hassio compatible)
VOLUME /data

WORKDIR /usr/local/app
ENTRYPOINT python3 /usr/local/app/emulated_hue.py