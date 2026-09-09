#!/usr/bin/env bash
set -euo pipefail

status_file="${YUMTECH_STATUS_FILE:-/home/hummingbot/yumtech-data/hummingbot-status.json}"
mkdir -p "$(dirname -- "$status_file")" /home/hummingbot/conf /home/hummingbot/conf/connectors
if [[ ! -e /home/hummingbot/conf/conf_client.yml ]]; then
  install -m 0600 /opt/yumtech-conf_client.yml /home/hummingbot/conf/conf_client.yml
fi
# Enforce the local-only privacy invariant even when an older persisted config
# is mounted from /data. These are Hummingbot's documented global keys.
for setting in "anonymized_metrics_mode: anonymized_metrics_disabled" "send_error_logs: false"; do
  key="${setting%%:*}"
  if grep -qE "^[[:space:]]*${key}:" /home/hummingbot/conf/conf_client.yml; then
    sed -i -E "s|^[[:space:]]*${key}:.*$|${setting}|" /home/hummingbot/conf/conf_client.yml
  else
    printf '%s\n' "$setting" >> /home/hummingbot/conf/conf_client.yml
  fi
done

write_status() {
  local state="$1"
  local temporary_file="${status_file}.tmp"
  printf '{"state":"%s","mode":"test","engine_version":"%s","telemetry_disabled":true,"live_orders_enabled":false,"strategy":"idle","control_action":null,"orders_submitted":0,"engine_process_running":false,"reason":"Test host başlatılıyor","updated_at_ms":%s}\n' \
    "$state" "${YUMTECH_ENGINE_VERSION}" "$(date +%s%3N)" >"$temporary_file"
  mv -f -- "$temporary_file" "$status_file"
}

write_status "idle"
trap 'write_status "stopped"' EXIT TERM INT

# The service is a test-only Hummingbot host. The local supervisor may start
# the reviewed PaperTrade strategy, but no command or environment value can
# select a live connector in this image.
if [[ "${YUMTECH_LIVE_TRADING_ENABLED,,}" == "true" ]]; then
  echo "Refusing to start live Hummingbot: live execution is not enabled in this build." >&2
  write_status "blocked"
  exit 78
fi

exec "$@"
