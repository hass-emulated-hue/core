FROM python:3.8-slim as builder

ENV PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple

RUN set -x \
    # Install buildtime packages
    && apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev

# build python wheels
WORKDIR /wheels
COPY . /tmp
RUN pip wheel uvloop cchardet aiodns brotlipy \
    && pip wheel -r /tmp/requirements.txt \
    && pip wheel /tmp
    
#### FINAL IMAGE
FROM python:3.8-slim AS final-image

WORKDIR /wheels
COPY --from=builder /wheels /wheels
RUN set -x \
    # Install runtime dependency packages
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tzdata \
        ca-certificates \
        openssl \
    # install emulated hue (and all it's dependencies) using the prebuilt wheels
    && pip install --no-cache-dir -f /wheels music_assistant \
    # cleanup
    && rm -rf /tmp/* \
    && rm -rf /wheels \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /root/*

ENV DEBUG=false
ENV VERBOSE=false
ENV HASS_URL=""
ENV HASS_TOKEN=""

EXPOSE 80/tcp
EXPOSE 443/tcp

VOLUME [ "/data" ]

ENTRYPOINT ["python3", "--config", "/data"]