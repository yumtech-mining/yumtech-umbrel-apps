#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${TEST_ROOT}"' EXIT

BIN_DIR="${TEST_ROOT}/bin"
INSTALL_DIR="${TEST_ROOT}/opt/yumtech"
DATA_DIR="${TEST_ROOT}/var/lib/yumtech"
COMMAND_PATH="${TEST_ROOT}/sbin/yumtech"
install -d -m 755 "${BIN_DIR}" "$(dirname "${COMMAND_PATH}")"
install -m 755 "${ROOT_DIR}/tests/fixtures/docker" "${BIN_DIR}/docker"
install -m 755 "${ROOT_DIR}/tests/fixtures/curl" "${BIN_DIR}/curl"

export PATH="${BIN_DIR}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export YUMTECH_TEST_SOURCE_ROOT="${ROOT_DIR}"
export YUMTECH_INSTALL_DIR="${INSTALL_DIR}"
export YUMTECH_DATA_DIR="${DATA_DIR}"
export YUMTECH_COMMAND_PATH="${COMMAND_PATH}"
export YUMTECH_RAW_BASE_URL="https://test.invalid/yumtech"
export BITCOIN_RPC_HOST="host.docker.internal"
export BITCOIN_RPC_PORT="8332"
export BITCOIN_RPC_USER="yumtech-test"
export BITCOIN_RPC_PASS="initial#rpc\$password"
export BITCOIN_ZMQ_HOST="host.docker.internal"
export BITCOIN_ZMQ_RAWBLOCK_PORT="28332"
export BITCOIN_ZMQ_HASHBLOCK_PORT="28334"
export YUMTECH_DASHBOARD_BIND="0.0.0.0"

bash "${ROOT_DIR}/install-linux.sh" install >/dev/null

[[ -x "${COMMAND_PATH}" ]]
[[ -f "${INSTALL_DIR}/docker-compose.yml" ]]
[[ "$(stat -c '%a' "${INSTALL_DIR}/.env")" == "600" ]]
[[ "$(stat -c '%a' "${DATA_DIR}/secrets")" == "700" ]]
grep -Fq "BITCOIN_RPC_PASS='initial#rpc\$password'" "${INSTALL_DIR}/.env"

environment_before="$(sha256sum "${INSTALL_DIR}/.env" | awk '{print $1}')"
bash "${ROOT_DIR}/install-linux.sh" update >/dev/null
environment_after="$(sha256sum "${INSTALL_DIR}/.env" | awk '{print $1}')"
[[ "${environment_before}" == "${environment_after}" ]]

database_password_before="$(grep '^YUMTECH_DB_PASSWORD=' "${INSTALL_DIR}/.env")"
export BITCOIN_RPC_PASS="reconfigured-password"
bash "${ROOT_DIR}/install-linux.sh" configure >/dev/null
database_password_after="$(grep '^YUMTECH_DB_PASSWORD=' "${INSTALL_DIR}/.env")"

[[ "${database_password_before}" == "${database_password_after}" ]]
grep -Fq "BITCOIN_RPC_PASS='reconfigured-password'" "${INSTALL_DIR}/.env"
[[ -f "${INSTALL_DIR}/.env.backup" ]]

bash "${ROOT_DIR}/install-linux.sh" uninstall >/dev/null
[[ ! -e "${COMMAND_PATH}" ]]
[[ -d "${DATA_DIR}" ]]

printf 'Linux installer end-to-end test passed.\n'
