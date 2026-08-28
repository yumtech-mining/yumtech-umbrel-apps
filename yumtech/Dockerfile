# Portable multi-architecture YUMTECH image.
FROM debian:trixie AS build-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    git \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-program-options-dev \
    libssl-dev \
    libpq-dev \
    libpqxx-dev \
    libzmq3-dev \
    cppzmq-dev \
    libsodium-dev \
    libsecp256k1-dev \
    capnproto \
    libcapnp-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY mkpool-src/ /build/

RUN bash scripts/gen-ipc-stubs.sh


FROM build-base AS test

RUN cmake -S . -B build-test \
    -GNinja \
    -DCMAKE_BUILD_TYPE=Release \
    -DMKPOOL_NATIVE=OFF \
    -DMKPOOL_ENABLE_LTO=OFF \
    -DMKPOOL_BUILD_TESTS=ON \
    -DMKPOOL_ENABLE_IPC=ON \
    && cmake --build build-test -j2 \
    && ctest --test-dir build-test --output-on-failure


FROM build-base AS builder

RUN cmake -S . -B build \
    -GNinja \
    -DCMAKE_BUILD_TYPE=Release \
    -DMKPOOL_NATIVE=OFF \
    -DMKPOOL_BUILD_TESTS=OFF \
    -DMKPOOL_ENABLE_IPC=ON \
    && cmake --build build -j2


FROM debian:trixie

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    python3 \
    python3-psycopg2 \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-program-options-dev \
    libssl-dev \
    libpq-dev \
    libpqxx-dev \
    libzmq3-dev \
    libsodium-dev \
    libsecp256k1-dev \
    libcapnp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/yumtech

COPY --from=builder /build/build/mkpool /usr/local/bin/mkpool
COPY mkpool-src/scripts/mkpool-ctl.py /opt/yumtech/mkpool-src/scripts/mkpool-ctl.py
COPY dashboard/ /opt/yumtech/dashboard/
COPY scripts/ /opt/yumtech/scripts/

RUN chmod +x \
    /usr/local/bin/mkpool \
    /opt/yumtech/mkpool-src/scripts/mkpool-ctl.py \
    /opt/yumtech/scripts/*.sh
