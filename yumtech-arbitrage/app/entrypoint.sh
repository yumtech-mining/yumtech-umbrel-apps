#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/secrets
  chown -R yumtech:yumtech /data
  chmod 0700 /data/secrets
  exec gosu yumtech uvicorn app.main:app --host 0.0.0.0 --port 8098 --proxy-headers --forwarded-allow-ips='*'
fi

mkdir -p /data/secrets
exec uvicorn app.main:app --host 0.0.0.0 --port 8098 --proxy-headers --forwarded-allow-ips='*'
