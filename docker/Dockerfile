# syntax=docker/dockerfile:experimental
ARG HASS_ARCH=amd64
ARG S6_ARCH=amd64
ARG RUST_ARCH=x86_64-unknown-linux-gnu
ARG BUILD_VERSION=latest

#####################################################################
#                                                                   #
# Build Wheels                                                      #
#                                                                   #
#####################################################################
FROM python:3.9-slim as wheels-builder
ARG RUST_ARCH

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
        libssl-dev

RUN set -x \
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
ARG S6_ARCH
WORKDIR /s6downloader

RUN set -x \
    && wget -O /tmp/s6-overlay.tar.gz "https://github.com/just-containers/s6-overlay/releases/download/v2.2.0.3/s6-overlay-${S6_ARCH}.tar.gz" \
    && mkdir -p /tmp/s6 \
    && tar zxvf /tmp/s6-overlay.tar.gz -C /tmp/s6 \
    && mv /tmp/s6/* .

#####################################################################
#                                                                   #
# Download and extract bashio                                       #
#                                                                   #
#####################################################################
FROM alpine:latest as bashiodownloader
WORKDIR /bashio

RUN set -x \
    && wget -O /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/v0.13.1.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar zxvf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib/* .

#####################################################################
#                                                                   #
# Final Image                                                       #
#                                                                   #
#####################################################################
FROM python:3.9-slim AS final-build
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
COPY docker/rootfs /

# Copy app
COPY emulated_hue emulated_hue

ENV S6_BEHAVIOUR_IF_STAGE2_FAILS=2

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
