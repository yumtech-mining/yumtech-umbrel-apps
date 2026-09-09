#!/bin/sh
set -eu
umask 077
mkdir -p /data/secrets
exec uvicorn app.main:app --host 0.0.0.0 --port 8098 --proxy-headers --forwarded-allow-ips='*'
