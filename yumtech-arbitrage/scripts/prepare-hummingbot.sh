#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
overlay_dir="${project_dir}/hummingbot-overlay"
lock_file="${overlay_dir}/UPSTREAM.lock"
destination="${1:-${project_dir}/.build/hummingbot}"

source "${lock_file}"

if [[ -e "${destination}" ]]; then
  echo "Destination already exists: ${destination}" >&2
  exit 1
fi

mkdir -p "$(dirname -- "${destination}")"
git clone --filter=blob:none --no-checkout "${repository}" "${destination}"
git -C "${destination}" fetch --depth=1 origin "refs/tags/${tag}:refs/tags/${tag}"
git -C "${destination}" checkout --detach "${tag}"

actual_commit="$(git -C "${destination}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${commit}" ]]; then
  echo "Pinned Hummingbot commit mismatch: expected ${commit}, got ${actual_commit}" >&2
  exit 1
fi

git -C "${destination}" apply --check "${overlay_dir}/patches/0001-disable-telemetry-by-default.patch"
git -C "${destination}" apply "${overlay_dir}/patches/0001-disable-telemetry-by-default.patch"
cp -R "${overlay_dir}/hummingbot/." "${destination}/hummingbot/"
cp -R "${overlay_dir}/test/." "${destination}/test/"

echo "Prepared Hummingbot ${tag} (${commit}) at ${destination}"

