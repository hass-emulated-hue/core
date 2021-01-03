ARG BUILD_VERSION

FROM ghcr.io/hass-emulated-hue/base-image

WORKDIR /app
COPY emulated_hue .

LABEL io.hass.version=${BUILD_VERSION}

ENV DEBUG=false
ENV VERBOSE=false
ENV HASS_URL=""
ENV HASS_TOKEN=""
