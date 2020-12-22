FROM python:3.8-slim as builder

ENV PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple

COPY requirements.txt /tmp/requirements.txt

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
RUN pip wheel uvloop cchardet aiodns brotlipy \
    && pip wheel -r /tmp/requirements.txt
    
#### FINAL IMAGE
FROM python:3.8-slim AS final-image

WORKDIR /wheels
COPY --from=builder /wheels /wheels
COPY . /app
RUN set -x \
    # Install runtime dependency packages
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tzdata \
        ca-certificates \
        openssl \
    # install prebuilt wheels
    && pip install --no-cache-dir -f /wheels -r /app/requirements.txt \
    # cleanup
    && rm -rf /tmp/* \
    && rm -rf /wheels \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /root/*

WORKDIR /app

ENV DEBUG=false
ENV VERBOSE=false
ENV HASS_URL=""
ENV HASS_TOKEN=""

EXPOSE 80/tcp
EXPOSE 443/tcp

VOLUME [ "/data" ]

ENTRYPOINT ["python3", "-m", "emulated_hue", "--data", "/data"]