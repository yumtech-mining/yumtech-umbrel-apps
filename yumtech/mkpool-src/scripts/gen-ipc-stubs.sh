#!/usr/bin/env bash
#
# Regenerate the Cap'n Proto C++ stubs for the Bitcoin Core mining IPC shim.
#
# Requires the Cap'n Proto compiler (capnp >= 1.0) on PATH:
#     apt-get install capnproto libcapnp-dev
#
# Run once (and after any schema change) before configuring with
# -DMKPOOL_ENABLE_IPC=ON. Output lands in src/ipc/gen/ and is git-ignored:
# the stubs are large, machine-generated, and reproducible from the schemas.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
schemas="${root}/src/ipc/schemas"
gen="${root}/src/ipc/gen"

if ! command -v capnp >/dev/null 2>&1; then
    echo "error: capnp not found on PATH (apt-get install capnproto)" >&2
    exit 1
fi

mkdir -p "${gen}"

# --src-prefix keeps the mp/ subdirectory in the output tree so the generated
# includes ("mp/proxy.capnp.h") resolve against src/ipc/gen as the include root.
# -I lets the "/mp/proxy.capnp" absolute import resolve to our local copy; the
# builtin "/capnp/c++.capnp" is found automatically by capnp.
capnp compile \
    --src-prefix="${schemas}" \
    -I"${schemas}" \
    -o "c++:${gen}" \
    "${schemas}/mp/proxy.capnp" \
    "${schemas}/common.capnp" \
    "${schemas}/mining.capnp" \
    "${schemas}/init.capnp"

echo "Generated Cap'n Proto stubs in ${gen}:"
find "${gen}" -name '*.capnp.c++' -printf '  %p\n'

