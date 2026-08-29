#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${YUMTECH_REPOSITORY:-yumtech-mining/yumtech-umbrel-apps}"
BRANCH="${YUMTECH_BRANCH:-main}"
INSTALL_ROOT="${YUMTECH_INSTALL_ROOT:-/opt/yumtech-ckpool-dashboard}"
ENV_FILE="/etc/default/yumtech-ckpool-dashboard"
UNIT_FILE="/etc/systemd/system/yumtech-ckpool-dashboard.service"
DASHBOARD_PORT="${DASHBOARD_PORT:-8096}"

if [[ ${EUID} -ne 0 ]]; then
  echo "Bu kurulum root yetkisi gerektirir: curl ... | sudo bash" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd bulunamadı; bu kurulum Raspberry Pi OS/Debian systemd içindir." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq python3 curl ca-certificates tar >/dev/null
fi

WORK_DIR="$(mktemp -d /tmp/yumtech-ckpool-dashboard.XXXXXX)"
cleanup() { rm -rf -- "${WORK_DIR}"; }
trap cleanup EXIT

LOCAL_SOURCE="${YUMTECH_SOURCE_DIR:-}"
if [[ -n ${LOCAL_SOURCE} && -f ${LOCAL_SOURCE}/yumtech_dashboard/__init__.py ]]; then
  SOURCE_DIR="${LOCAL_SOURCE}"
else
  ARCHIVE="${WORK_DIR}/source.tar.gz"
  curl -fsSL --retry 3 "https://github.com/${REPOSITORY}/archive/refs/heads/${BRANCH}.tar.gz" -o "${ARCHIVE}"
  tar -xzf "${ARCHIVE}" -C "${WORK_DIR}"
  SOURCE_DIR="$(find "${WORK_DIR}" -mindepth 1 -maxdepth 4 -type f -path '*/yumtech_dashboard/__init__.py' -printf '%h\n' | sed 's#/yumtech_dashboard$##' | head -n 1)"
fi

if [[ -z ${SOURCE_DIR:-} || ! -f ${SOURCE_DIR}/server.py ]]; then
  echo "İndirilen arşivde YUMTECH dashboard kaynakları bulunamadı." >&2
  exit 1
fi

CKPOOL_CONFIG="${CKPOOL_CONFIG:-}"
if [[ -z ${CKPOOL_CONFIG} ]]; then
  for candidate in /etc/ckpool/ckpool.conf /etc/ckpool.conf /usr/local/etc/ckpool.conf; do
    if [[ -f ${candidate} ]]; then CKPOOL_CONFIG="${candidate}"; break; fi
  done
fi
CKPOOL_CONFIG="${CKPOOL_CONFIG:-/etc/ckpool/ckpool.conf}"

CKPOOL_USER="$(systemctl show -p User --value ckpool.service 2>/dev/null || true)"
CKPOOL_GROUP="$(systemctl show -p Group --value ckpool.service 2>/dev/null || true)"
CKPOOL_USER="${CKPOOL_USER:-root}"
if [[ -z ${CKPOOL_GROUP} ]]; then
  CKPOOL_GROUP="$(id -gn "${CKPOOL_USER}" 2>/dev/null || echo root)"
fi

VERSION="$(python3 -c 'import pathlib,re; p=pathlib.Path("'"${SOURCE_DIR}"'/yumtech_dashboard/__init__.py").read_text(); print(re.search(r"__version__\s*=\s*[\"'"'"']([^\"'"'"']+)",p).group(1))')"
RELEASE="${INSTALL_ROOT}/releases/${VERSION}-$(date -u +%Y%m%d%H%M%S)"
install -d -m 755 "${RELEASE}"
cp -a "${SOURCE_DIR}/yumtech_dashboard" "${RELEASE}/"
install -m 755 "${SOURCE_DIR}/server.py" "${RELEASE}/server.py"
install -m 755 "${SOURCE_DIR}/install.sh" "${RELEASE}/install.sh"
install -m 755 "${SOURCE_DIR}/uninstall.sh" "${RELEASE}/uninstall.sh"
ln -sfn "${RELEASE}" "${INSTALL_ROOT}/current.next"
mv -Tf "${INSTALL_ROOT}/current.next" "${INSTALL_ROOT}/current"

if [[ ! -f ${ENV_FILE} ]]; then
  install -d -m 755 /etc/default
  {
    echo "DASHBOARD_HOST=0.0.0.0"
    echo "DASHBOARD_PORT=${DASHBOARD_PORT}"
    echo "CKPOOL_CONFIG=${CKPOOL_CONFIG}"
    echo "DASHBOARD_RETENTION_DAYS=30"
    echo "# İnternete açacaksanız aşağıdaki iki değeri birlikte ayarlayın:"
    echo "# DASHBOARD_USER=yumtech"
    echo "# DASHBOARD_PASSWORD=guclu-bir-parola"
  } >"${ENV_FILE}"
  chmod 640 "${ENV_FILE}"
fi

install -d -m 755 "${INSTALL_ROOT}/releases"
install -d -o "${CKPOOL_USER}" -g "${CKPOOL_GROUP}" -m 750 /var/lib/yumtech-ckpool-dashboard

{
  echo "[Unit]"
  echo "Description=YUMTECH CKPool Dashboard"
  echo "Wants=network-online.target"
  echo "After=network-online.target ckpool.service bitcoind.service bitcoin-node.service"
  echo
  echo "[Service]"
  echo "Type=simple"
  echo "User=${CKPOOL_USER}"
  echo "Group=${CKPOOL_GROUP}"
  echo "EnvironmentFile=-${ENV_FILE}"
  echo "WorkingDirectory=${INSTALL_ROOT}/current"
  echo "ExecStart=/usr/bin/python3 -m yumtech_dashboard"
  echo "Restart=on-failure"
  echo "RestartSec=3"
  echo "NoNewPrivileges=true"
  echo "PrivateTmp=false"
  echo "ProtectSystem=full"
  echo "ProtectHome=true"
  echo "ReadWritePaths=/var/lib/yumtech-ckpool-dashboard"
  echo
  echo "[Install]"
  echo "WantedBy=multi-user.target"
} >"${UNIT_FILE}"

systemctl daemon-reload
systemctl enable --now yumtech-ckpool-dashboard.service

for _ in {1..20}; do
  if curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! systemctl is-active --quiet yumtech-ckpool-dashboard.service; then
  echo "Dashboard başlatılamadı. Son kayıtlar:" >&2
  journalctl -u yumtech-ckpool-dashboard.service -n 50 --no-pager >&2
  exit 1
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "YUMTECH CKPool Dashboard ${VERSION} kuruldu."
echo "Adres: http://${LAN_IP:-RASPBERRY_PI_IP}:${DASHBOARD_PORT}"
echo "Durum: systemctl status yumtech-ckpool-dashboard"
echo "Log:   journalctl -u yumtech-ckpool-dashboard -f"
