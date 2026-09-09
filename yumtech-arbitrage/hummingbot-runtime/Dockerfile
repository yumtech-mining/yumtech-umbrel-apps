# YUMTECH ships the official multi-architecture Hummingbot v2.16.0 image and
# only overlays the reviewed exchange connectors. No forked engine is built.
FROM hummingbot/hummingbot:version-2.16.0

USER root
COPY hummingbot-overlay/hummingbot/ /home/hummingbot/hummingbot/
COPY hummingbot-overlay/patches/0001-disable-telemetry-by-default.patch /opt/yumtech-telemetry.patch
COPY hummingbot/conf_client.yml /opt/yumtech-conf_client.yml
COPY hummingbot-runtime/entrypoint.sh /usr/local/bin/yumtech-hummingbot

RUN apt-get update && apt-get install -y --no-install-recommends patch && \
    cd /home/hummingbot && patch --forward --batch -p1 < /opt/yumtech-telemetry.patch && \
    rm -rf /var/lib/apt/lists/*
RUN chmod 0555 /usr/local/bin/yumtech-hummingbot && \
    mkdir -p /home/hummingbot/conf /home/hummingbot/logs /home/hummingbot/data /home/hummingbot/yumtech-data

ENV YUMTECH_ENGINE_VERSION=v2.16.0 \
    YUMTECH_TELEMETRY_DISABLED=true \
    YUMTECH_LIVE_TRADING_ENABLED=false

ENTRYPOINT ["/usr/local/bin/yumtech-hummingbot"]
CMD ["tail", "-f", "/dev/null"]
