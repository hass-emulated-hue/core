# syntax=docker/dockerfile:experimental
ARG BUILD_VERSION

#####################################################################
#                                                                   #
# Download and extract rootfs                                       #
#                                                                   #
#####################################################################
FROM alpine:latest as s6-base-downloader

WORKDIR /base

RUN wget -O base.tar.gz https://github.com/hass-emulated-hue/s6-overlay-base/archive/master.tar.gz \
    && tar zxvf base.tar.gz --strip 1 -C .


#####################################################################
#                                                                   #
# Final Image                                                       #
#                                                                   #
#####################################################################
FROM ghcr.io/hass-emulated-hue/base-image
# Required to presist build arg
ARG BUILD_VERSION

# Copy root filesystem
COPY --from=s6-base-downloader /base/rootfs/ /
# Copy app
COPY emulated_hue emulated_hue

LABEL io.hass.version=${BUILD_VERSION}

ENV DEBUG=false
ENV VERBOSE=false
ENV HASS_URL=""
ENV HASS_TOKEN=""
