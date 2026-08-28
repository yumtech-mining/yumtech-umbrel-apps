#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${TEST_ROOT}"' EXIT

export YUMTECH_LIBRARY_ONLY=1
export YUMTECH_INSTALL_DIR="${TEST_ROOT}/install"
export YUMTECH_DATA_DIR="${TEST_ROOT}/data"

# shellcheck source=../install-linux.sh
source "${ROOT_DIR}/install-linux.sh"

install -d -m 755 "${INSTALL_DIR}"

expected_data_dir="/srv/YUMTECH data"
expected_password="$(printf 'ab%.0s' {1..32})"
special_rpc_password="rpc#pass\$word\\with'quote"

{
    printf 'YUMTECH_DATA_DIR=%s\n' "$(env_quote "${expected_data_dir}")"
    printf 'YUMTECH_DB_PASSWORD=%s\n' "$(env_quote "${expected_password}")"
    printf 'BITCOIN_RPC_PASS=%s\n' "$(env_quote "${special_rpc_password}")"
} >"${ENV_FILE}"

[[ "$(read_managed_env_value YUMTECH_DATA_DIR)" == "${expected_data_dir}" ]]
[[ "$(read_managed_env_value YUMTECH_DB_PASSWORD)" == "${expected_password}" ]]
[[ "$(read_managed_env_value BITCOIN_RPC_PASS)" == "${special_rpc_password}" ]]

validate_port BITCOIN_RPC_PORT 8332
validate_port BITCOIN_ZMQ_RAWBLOCK_PORT 28332
validate_plain_value BITCOIN_RPC_HOST host.docker.internal

printf 'Linux installer helper tests passed.\n'
