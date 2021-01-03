FROM ghcr.io/hass-emulated-hue/base-image

WORKDIR /app
COPY emulated_hue .

ENV DEBUG=false
ENV VERBOSE=false
ENV HASS_URL=""
ENV HASS_TOKEN=""

EXPOSE 80/tcp
EXPOSE 443/tcp

VOLUME [ "/data" ]

CMD ["python3", "-m", "emulated_hue", "--data", "/data"]