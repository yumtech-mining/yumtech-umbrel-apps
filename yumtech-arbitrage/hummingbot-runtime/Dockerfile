# YUMTECH ships the official multi-architecture Hummingbot v2.16.0 image and
# only overlays the reviewed exchange connectors. No forked engine is built.
FROM hummingbot/hummingbot:version-2.16.0

USER root
COPY hummingbot-overlay/hummingbot/ /home/hummingbot/hummingbot/
COPY hummingbot/conf_client.yml /opt/yumtech-conf_client.yml
COPY hummingbot-runtime/entrypoint.sh /usr/local/bin/yumtech-hummingbot

RUN chmod 0555 /usr/local/bin/yumtech-hummingbot && \
    mkdir -p /home/hummingbot/conf /home/hummingbot/logs /home/hummingbot/data /home/hummingbot/yumtech-data

ENV YUMTECH_ENGINE_VERSION=v2.16.0 \
    YUMTECH_TELEMETRY_DISABLED=true \
    YUMTECH_LIVE_TRADING_ENABLED=false

ENTRYPOINT ["/usr/local/bin/yumtech-hummingbot"]
CMD ["tail", "-f", "/dev/null"]
