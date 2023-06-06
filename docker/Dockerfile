# syntax=docker/dockerfile:experimental
ARG HASS_ARCH=amd64
ARG BUILD_VERSION=latest
ARG PYTHON_VERSION="3.11"
ARG BASHIO_VERSION="v0.15.0"

#####################################################################
#                                                                   #
# Build Wheels                                                      #
#                                                                   #
#####################################################################
FROM python:${PYTHON_VERSION}-slim as wheels-builder
ARG HASS_ARCH

ENV PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple
ENV PATH="${PATH}:/root/.cargo/bin"

# Install buildtime packages
RUN set -x \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    gcc \
    git \
    libffi-dev \
    libssl-dev \
    pkg-config

RUN set -x \
    \
    && if [ ${HASS_ARCH} = "i386" ]; then RUST_ARCH="i686-unknown-linux-gnu"; fi \
    && if [ ${HASS_ARCH} = "amd64" ]; then RUST_ARCH="x86_64-unknown-linux-gnu"; fi \
    && if [ ${HASS_ARCH} = "armv6" ]; then RUST_ARCH="arm-unknown-linux-gnueabi"; fi \
    && if [ ${HASS_ARCH} = "armv7" ]; then RUST_ARCH="armv7-unknown-linux-gnueabihf"; fi \
    && if [ ${HASS_ARCH} = "aarch64" ]; then RUST_ARCH="aarch64-unknown-linux-gnu"; fi \
    \
    && curl -o rustup-init https://static.rust-lang.org/rustup/dist/${RUST_ARCH}/rustup-init \
    && chmod +x rustup-init \
    && ./rustup-init -y --no-modify-path --profile minimal --default-host ${RUST_ARCH}

WORKDIR /wheels
COPY requirements.txt .

# build python wheels
RUN set -x \
    && pip wheel -r requirements.txt

#####################################################################
#                                                                   #
# Download and extract s6 overlay                                   #
#                                                                   #
#####################################################################
FROM alpine:latest as s6downloader
# Required to persist build arg
ARG HASS_ARCH
WORKDIR /s6downloader

RUN set -x \
    \
    && if [ ${HASS_ARCH} = "i386" ]; then S6_ARCH="i686"; fi \
    && if [ ${HASS_ARCH} = "amd64" ]; then S6_ARCH="x86_64"; fi \
    && if [ ${HASS_ARCH} = "armv6" ]; then S6_ARCH="arm"; fi \
    && if [ ${HASS_ARCH} = "armv7" ]; then S6_ARCH="armhf"; fi \
    && if [ ${HASS_ARCH} = "aarch64" ]; then S6_ARCH="aarch64"; fi \
    \
    && S6_OVERLAY_VERSION=$(wget --no-check-certificate -qO - https://api.github.com/repos/just-containers/s6-overlay/releases/latest | awk '/tag_name/{print $4;exit}' FS='[""]') \
    && S6_OVERLAY_VERSION=${S6_OVERLAY_VERSION:1} \
    && wget -O /tmp/s6-overlay-arch.tar.xz "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" \
    && wget -O /tmp/s6-overlay-noarch.tar.xz "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" \
    && mkdir -p /tmp/s6 \
    && tar -Jxvf /tmp/s6-overlay-noarch.tar.xz -C /tmp/s6 \
    && tar -Jxvf /tmp/s6-overlay-arch.tar.xz -C /tmp/s6 \
    && cp -r /tmp/s6/* .

#####################################################################
#                                                                   #
# Download and extract bashio                                       #
#                                                                   #
#####################################################################
FROM alpine:latest as bashiodownloader
ARG BASHIO_VERSION
WORKDIR /bashio

RUN set -x \
    && wget -O /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar zxvf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib/* .

#####################################################################
#                                                                   #
# Final Image                                                       #
#                                                                   #
#####################################################################
FROM python:${PYTHON_VERSION}-slim AS final-build
WORKDIR /app

ENV DEBIAN_FRONTEND="noninteractive"

RUN set -x \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    jq \
    openssl \
    tzdata \
    # cleanup
    && rm -rf /tmp/* \
    && rm -rf /var/lib/apt/lists/*

# Install bashio
COPY --from=bashiodownloader /bashio /usr/lib/bashio
RUN ln -s /usr/lib/bashio/bashio /usr/bin/bashio

# Install s6 overlay
COPY --from=s6downloader /s6downloader /

# https://github.com/moby/buildkit/blob/master/frontend/dockerfile/docs/syntax.md#build-mounts-run---mount
# Install pip dependencies with built wheels
RUN --mount=type=bind,target=/tmp/wheels,source=/wheels,from=wheels-builder,rw \
    set -x \
    && pip install --no-cache-dir -f /tmp/wheels -r /tmp/wheels/requirements.txt

# Copy root filesystem
COPY --chmod=0755 docker/rootfs /

# Copy app
COPY emulated_hue emulated_hue

ENV S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

# Required to persist build arg
ARG BUILD_VERSION
ARG HASS_ARCH
LABEL \
    io.hass.version=${BUILD_VERSION} \
    io.hass.name="Hass Emulated Hue" \
    io.hass.description="Hue Emulation for Home Assistant" \
    io.hass.arch="${HASS_ARCH}" \
    io.hass.type="addon"

CMD ["/init"]
