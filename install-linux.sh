#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly YUMTECH_REPOSITORY="yumtech-mining/yumtech-umbrel-apps"
readonly YUMTECH_RAW_BASE_DEFAULT="https://raw.githubusercontent.com/${YUMTECH_REPOSITORY}/main"
INSTALL_DIR="${YUMTECH_INSTALL_DIR:-/opt/yumtech}"
DATA_DIR="${YUMTECH_DATA_DIR:-/var/lib/yumtech}"
DATA_DIR_WAS_OVERRIDDEN="${YUMTECH_DATA_DIR+x}"
RAW_BASE="${YUMTECH_RAW_BASE_URL:-${YUMTECH_RAW_BASE_DEFAULT}}"
COMPOSE_FILE="${INSTALL_DIR}/docker-compose.yml"
ENV_FILE="${INSTALL_DIR}/.env"
COMMAND_PATH="${YUMTECH_COMMAND_PATH:-/usr/local/sbin/yumtech}"
ACTION="${1:-install}"

log() {
    printf '\n[YUMTECH] %s\n' "$*"
}

warn() {
    printf '\n[YUMTECH] UYARI: %s\n' "$*" >&2
}

die() {
    printf '\n[YUMTECH] HATA: %s\n' "$*" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\n[YUMTECH] Kurulum %s. Satır: %s\n' \
        "başarısız oldu" "${BASH_LINENO[0]:-bilinmiyor}" >&2
    exit "${exit_code}"
}
trap on_error ERR

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "Bu komutu sudo ile çalıştırın."
    fi
}

require_linux() {
    [[ "$(uname -s)" == "Linux" ]] || die "Yalnızca Linux destekleniyor."
    case "$(uname -m)" in
        x86_64|amd64|aarch64|arm64) ;;
        *) die "Desteklenmeyen mimari: $(uname -m). amd64 veya arm64 gerekir." ;;
    esac
}

read_managed_env_value() {
    local key="$1"
    local line=""
    local value=""

    [[ -f "${ENV_FILE}" ]] || return 1
    line="$(grep -m1 -E "^${key}=" "${ENV_FILE}" 2>/dev/null || true)"
    [[ -n "${line}" ]] || return 1
    value="${line#*=}"

    if [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
        value="${value:1:${#value}-2}"
        value="${value//\\\'/\'}"
        value="${value//\\\\/\\}"
    fi
    printf '%s' "${value}"
}

load_existing_paths() {
    local existing_data_dir=""

    if [[ -z "${DATA_DIR_WAS_OVERRIDDEN}" ]]; then
        existing_data_dir="$(read_managed_env_value YUMTECH_DATA_DIR || true)"
        if [[ -n "${existing_data_dir}" ]]; then
            DATA_DIR="${existing_data_dir}"
        fi
    fi
}

install_base_packages() {
    local missing=()
    command -v curl >/dev/null 2>&1 || missing+=(curl)
    command -v openssl >/dev/null 2>&1 || missing+=(openssl)

    if ((${#missing[@]} == 0)); then
        return
    fi

    command -v apt-get >/dev/null 2>&1 || \
        die "Eksik araçlar: ${missing[*]}. Otomatik paket kurulumu Debian/Ubuntu gerektirir."

    log "Gerekli temel paketler kuruluyor"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl openssl
}

has_compose_v2() {
    if docker compose version >/dev/null 2>&1; then
        return 0
    fi
    if command -v docker-compose >/dev/null 2>&1 && \
       docker-compose version 2>/dev/null | grep -Eq '(^|[[:space:]])v?2\.'; then
        return 0
    fi
    return 1
}

install_docker() {
    if command -v docker >/dev/null 2>&1 && has_compose_v2; then
        if ! docker info >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
            systemctl start docker
        fi
        docker info >/dev/null 2>&1 || die "Docker servisi çalışmıyor."
        return
    fi

    command -v apt-get >/dev/null 2>&1 || \
        die "Docker Compose bulunamadı. Docker Engine ve Compose v2 kurun."

    log "Docker Engine ve Docker Compose kuruluyor"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io

    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-v2; then
        if ! DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin; then
            DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose
        fi
    fi

    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable --now docker
    fi

    command -v docker >/dev/null 2>&1 || die "Docker kurulamadı."
    docker info >/dev/null 2>&1 || die "Docker servisi çalışmıyor."
    has_compose_v2 || die "Docker Compose v2 kurulamadı."
}

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose \
            --project-name yumtech \
            --project-directory "${INSTALL_DIR}" \
            --env-file "${ENV_FILE}" \
            --file "${COMPOSE_FILE}" \
            "$@"
    else
        docker-compose \
            --project-name yumtech \
            --project-directory "${INSTALL_DIR}" \
            --env-file "${ENV_FILE}" \
            --file "${COMPOSE_FILE}" \
            "$@"
    fi
}

has_tty() {
    [[ -r /dev/tty && -w /dev/tty ]]
}

prompt_value() {
    local variable_name="$1"
    local prompt_text="$2"
    local default_value="${3:-}"
    local secret="${4:-false}"
    local current_value="${!variable_name:-}"
    local entered=""

    if [[ -n "${current_value}" ]]; then
        printf -v "${variable_name}" '%s' "${current_value}"
        return
    fi

    if ! has_tty; then
        [[ -n "${default_value}" ]] || \
            die "${variable_name} ayarlanmalı. Etkileşimli terminal bulunamadı."
        printf -v "${variable_name}" '%s' "${default_value}"
        return
    fi

    if [[ "${secret}" == "true" ]]; then
        printf '%s: ' "${prompt_text}" >/dev/tty
        IFS= read -r -s entered </dev/tty
        printf '\n' >/dev/tty
    elif [[ -n "${default_value}" ]]; then
        printf '%s [%s]: ' "${prompt_text}" "${default_value}" >/dev/tty
        IFS= read -r entered </dev/tty
    else
        printf '%s: ' "${prompt_text}" >/dev/tty
        IFS= read -r entered </dev/tty
    fi

    entered="${entered:-${default_value}}"
    [[ -n "${entered}" ]] || die "${prompt_text} boş bırakılamaz."
    printf -v "${variable_name}" '%s' "${entered}"
}

validate_plain_value() {
    local name="$1"
    local value="$2"
    [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || \
        die "${name} satır sonu içeremez."
}

validate_port() {
    local name="$1"
    local value="$2"
    [[ "${value}" =~ ^[0-9]+$ ]] || die "${name} sayısal olmalı."
    ((value >= 1 && value <= 65535)) || die "${name} 1-65535 arasında olmalı."
}

env_quote() {
    local value="$1"
    validate_plain_value "Ortam değeri" "${value}"
    value="${value//\\/\\\\}"
    value="${value//\'/\\\'}"
    printf "'%s'" "${value}"
}

write_environment() {
    local temporary
    local db_password=""

    prompt_value BITCOIN_RPC_HOST \
        "Bitcoin Core/Knots RPC adresi" "host.docker.internal"
    prompt_value BITCOIN_RPC_PORT "Bitcoin RPC portu" "8332"
    prompt_value BITCOIN_RPC_USER "Bitcoin RPC kullanıcı adı"
    prompt_value BITCOIN_RPC_PASS "Bitcoin RPC parolası" "" true
    prompt_value BITCOIN_ZMQ_HOST \
        "Bitcoin ZMQ adresi" "${BITCOIN_RPC_HOST}"
    prompt_value BITCOIN_ZMQ_RAWBLOCK_PORT "ZMQ rawblock portu" "28332"
    prompt_value BITCOIN_ZMQ_HASHBLOCK_PORT "ZMQ hashblock portu" "28334"
    prompt_value YUMTECH_DASHBOARD_BIND "Dashboard dinleme adresi" "0.0.0.0"

    validate_port BITCOIN_RPC_PORT "${BITCOIN_RPC_PORT}"
    validate_port BITCOIN_ZMQ_RAWBLOCK_PORT "${BITCOIN_ZMQ_RAWBLOCK_PORT}"
    validate_port BITCOIN_ZMQ_HASHBLOCK_PORT "${BITCOIN_ZMQ_HASHBLOCK_PORT}"

    for variable_name in \
        BITCOIN_RPC_HOST BITCOIN_RPC_USER BITCOIN_RPC_PASS \
        BITCOIN_ZMQ_HOST YUMTECH_DASHBOARD_BIND DATA_DIR; do
        validate_plain_value "${variable_name}" "${!variable_name}"
    done

    db_password="$(read_managed_env_value YUMTECH_DB_PASSWORD || true)"
    if [[ ! "${db_password}" =~ ^[0-9a-fA-F]{64}$ ]]; then
        db_password="$(openssl rand -hex 32)"
    fi
    temporary="$(mktemp "${INSTALL_DIR}/.env.XXXXXX")"

    {
        printf 'YUMTECH_DATA_DIR=%s\n' "$(env_quote "${DATA_DIR}")"
        printf 'YUMTECH_DB_PASSWORD=%s\n' "$(env_quote "${db_password}")"
        printf 'BITCOIN_RPC_HOST=%s\n' "$(env_quote "${BITCOIN_RPC_HOST}")"
        printf 'BITCOIN_RPC_PORT=%s\n' "$(env_quote "${BITCOIN_RPC_PORT}")"
        printf 'BITCOIN_RPC_USER=%s\n' "$(env_quote "${BITCOIN_RPC_USER}")"
        printf 'BITCOIN_RPC_PASS=%s\n' "$(env_quote "${BITCOIN_RPC_PASS}")"
        printf 'BITCOIN_ZMQ_HOST=%s\n' "$(env_quote "${BITCOIN_ZMQ_HOST}")"
        printf 'BITCOIN_ZMQ_RAWBLOCK_PORT=%s\n' \
            "$(env_quote "${BITCOIN_ZMQ_RAWBLOCK_PORT}")"
        printf 'BITCOIN_ZMQ_HASHBLOCK_PORT=%s\n' \
            "$(env_quote "${BITCOIN_ZMQ_HASHBLOCK_PORT}")"
        printf 'YUMTECH_DASHBOARD_BIND=%s\n' \
            "$(env_quote "${YUMTECH_DASHBOARD_BIND}")"
    } >"${temporary}"

    chmod 600 "${temporary}"
    if [[ -f "${ENV_FILE}" ]]; then
        cp -a "${ENV_FILE}" "${ENV_FILE}.backup"
    fi
    mv -f "${temporary}" "${ENV_FILE}"
}

download_runtime_files() {
    local compose_temporary
    local command_temporary

    install -d -m 755 "${INSTALL_DIR}"
    compose_temporary="$(mktemp "${INSTALL_DIR}/docker-compose.yml.XXXXXX")"
    command_temporary="$(mktemp "${INSTALL_DIR}/yumtech.XXXXXX")"

    curl --fail --silent --show-error --location \
        "${RAW_BASE}/linux/docker-compose.yml" \
        --output "${compose_temporary}"
    curl --fail --silent --show-error --location \
        "${RAW_BASE}/install-linux.sh" \
        --output "${command_temporary}"

    chmod 644 "${compose_temporary}"
    chmod 755 "${command_temporary}"
    mv -f "${compose_temporary}" "${COMPOSE_FILE}"
    install -m 755 "${command_temporary}" "${COMMAND_PATH}"
    rm -f "${command_temporary}"
}

prepare_data_directories() {
    install -d -m 755 \
        "${DATA_DIR}" \
        "${DATA_DIR}/postgres" \
        "${DATA_DIR}/mkpool" \
        "${DATA_DIR}/runtime" \
        "${DATA_DIR}/public"
    install -d -m 700 "${DATA_DIR}/secrets"
}

wait_for_dashboard() {
    local attempt

    for attempt in $(seq 1 60); do
        if compose exec -T dashboard python3 -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/api/overview', timeout=3).read()" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

show_connection_summary() {
    local host_ip
    local node_online="false"
    local node_response=""

    host_ip="$(
        { hostname -I 2>/dev/null || true; } | awk '{print $1}'
    )"
    host_ip="${host_ip:-SUNUCU_IP_ADRESI}"
    node_response="$(
        compose exec -T dashboard python3 -c \
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8095/api/node', timeout=5).read().decode())" \
            2>/dev/null || true
    )"
    if grep -Eq '"online"[[:space:]]*:[[:space:]]*true' <<<"${node_response}"; then
        node_online="true"
    fi

    printf '\nYUMTECH Linux kurulumu tamamlandı.\n'
    printf 'Dashboard : http://%s:8095\n' "${host_ip}"
    printf 'Stratum V1: stratum+tcp://%s:3333\n' "${host_ip}"
    printf 'Stratum V2: %s:3340\n' "${host_ip}"
    printf 'Durum      : sudo yumtech status\n'
    printf 'Loglar     : sudo yumtech logs\n'
    printf 'Güncelleme : sudo yumtech update\n'

    if [[ "${node_online}" != "true" ]]; then
        warn "Dashboard çalışıyor ancak Bitcoin RPC bağlantısı henüz doğrulanamadı."
        warn "Node üzerinde RPC/ZMQ dinleme adreslerini ve Docker ağı izinlerini kontrol edin."
    fi

    warn "8095 dashboard portunu kimlik doğrulama olmadan doğrudan internete açmayın."
}

start_or_update() {
    local reconfigure="${1:-false}"

    load_existing_paths
    [[ "${INSTALL_DIR}" == /* ]] || die "YUMTECH_INSTALL_DIR mutlak bir yol olmalı."
    [[ "${DATA_DIR}" == /* ]] || die "YUMTECH_DATA_DIR mutlak bir yol olmalı."

    install_base_packages
    install_docker
    download_runtime_files

    # Continue with the freshly downloaded installer so an older local
    # yumtech command can safely adopt future configuration changes.
    if [[ "${YUMTECH_BOOTSTRAPPED:-0}" != "1" ]]; then
        export YUMTECH_BOOTSTRAPPED=1
        exec "${COMMAND_PATH}" "${ACTION}"
    fi

    prepare_data_directories

    if [[ "${reconfigure}" == "true" || ! -f "${ENV_FILE}" ]]; then
        write_environment
    else
        log "Mevcut yapılandırma, veritabanı ve SV2 anahtarı korunuyor"
    fi

    compose config >/dev/null
    log "YUMTECH imajları indiriliyor"
    compose pull
    log "YUMTECH servisleri başlatılıyor"
    compose up -d --remove-orphans

    if ! wait_for_dashboard; then
        compose ps || true
        compose logs --tail 100 dashboard mkpool || true
        die "Dashboard 120 saniye içinde hazır olmadı. Yukarıdaki logları kontrol edin."
    fi

    show_connection_summary
}

show_status() {
    [[ -f "${COMPOSE_FILE}" && -f "${ENV_FILE}" ]] || \
        die "YUMTECH Linux kurulumu bulunamadı."
    compose ps
    printf '\nDashboard sağlık kontrolü:\n'
    compose exec -T dashboard python3 -c \
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8095/api/node', timeout=5).read().decode())" \
        2>/dev/null || true
    printf '\n'
}

show_logs() {
    [[ -f "${COMPOSE_FILE}" && -f "${ENV_FILE}" ]] || \
        die "YUMTECH Linux kurulumu bulunamadı."
    compose logs --tail 200 -f dashboard mkpool db
}

uninstall_services() {
    [[ -f "${COMPOSE_FILE}" && -f "${ENV_FILE}" ]] || \
        die "YUMTECH Linux kurulumu bulunamadı."
    compose down --remove-orphans
    rm -f "${COMMAND_PATH}"
    warn "Servisler kaldırıldı. Madencilik verileri güvenlik için ${DATA_DIR} altında korundu."
    warn "Verileri de silmek isterseniz bu dizini ayrıca ve bilinçli olarak kaldırın."
}

main() {
    require_root
    require_linux
    load_existing_paths

    case "${ACTION}" in
        install)
            start_or_update false
            ;;
        update)
            start_or_update false
            ;;
        configure|reconfigure)
            start_or_update true
            ;;
        status)
            install_base_packages
            install_docker
            show_status
            ;;
        logs)
            install_base_packages
            install_docker
            show_logs
            ;;
        uninstall)
            uninstall_services
            ;;
        *)
            die "Bilinmeyen işlem: ${ACTION}. install, update, configure, status, logs veya uninstall kullanın."
            ;;
    esac
}

if [[ "${YUMTECH_LIBRARY_ONLY:-0}" != "1" ]]; then
    main "$@"
fi
