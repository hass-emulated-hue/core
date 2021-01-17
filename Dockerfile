ARG BUILD_VERSION
FROM ghcr.io/hass-emulated-hue/base-image
# Required to persist build arg
ARG BUILD_VERSION

# Copy app
COPY emulated_hue emulated_hue

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        supervisor \
    && rm -rf /var/lib/apt/lists/*


COPY ./supervisord.conf /usr/local/supervisord.conf

LABEL io.hass.version=${BUILD_VERSION}

CMD ["supervisord", "-c", "/usr/local/supervisord.conf"]
