ARG BUILD_FROM=alpine:3.10
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Copy Python requirements file
COPY requirements.txt /tmp/

RUN \
    apk add --no-cache --virtual .build-dependencies \
        build-base \
        cmake \
        libuv-dev \
        libffi-dev \
        python3-dev \
        openssl-dev \
    && apk add --no-cache \
        python3 \
        openssl \
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
COPY run.py /usr/local/app/

# Default volume (hassio compatible)
VOLUME /data

WORKDIR /usr/local/app
ENTRYPOINT /usr/local/app/run.py