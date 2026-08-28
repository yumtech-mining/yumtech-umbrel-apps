// SPDX-License-Identifier: GPL-3.0
// Copyright (c) 2025-2026 Mecanik1337 <contact@mecanik.dev>
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.
//
// File:        ipc_mining.hpp
// Description: Bitcoin Core mining IPC (Cap'n Proto) client - pure C++ facade.
// Created:     2026-07-20
// Project:     mkpool - Modern Multi-Coin Solo Mining Pool

#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

// All Cap'n Proto / kj complexity is confined to ipc_mining.cpp behind a pimpl,
// so this header is includable anywhere without pulling in capnp headers. When
// the build is configured without -DMKPOOL_ENABLE_IPC (no HAVE_CAPNP), the
// implementation TU is not compiled and callers must guard use with
// #ifdef HAVE_CAPNP; the declarations below remain valid either way.
namespace mkpool::ipc {

// Current chain tip as reported by Mining.getTip / Mining.waitTipChanged.
struct Tip {
    std::string  hash;      // 64-char big-endian display hex (as miners see it)
    std::int32_t height{0};
};

// Plain mirror of an IPC BlockTemplate, filled by the shim so the generator can
// synthesize a getblocktemplate-shaped JSON without any Cap'n Proto type
// escaping the shim. Declared here so the generator can consume templates
// through this plain struct while the facade stays stable.
struct Template {
    std::uint64_t handle{0};                       // opaque id of the retained node-side BlockTemplate (for submit_solution)
    std::int32_t  height{0};
    std::uint32_t version{0};                      // block header version (from getBlockHeader)
    std::uint32_t curtime{0};                      // block header nTime
    std::string   bits;                            // compact nBits, big-endian hex (8 chars)
    std::string   prevhash;                        // big-endian display hex (64 chars)
    std::int64_t  coinbase_value{0};              // block_reward_remaining (sats) available to the pool's payout outputs
    std::string   witness_commitment;              // segwit commitment SCRIPT hex extracted from required outputs; empty if none
    std::vector<std::string> merkle_branch;        // node-precomputed coinbase merkle path, raw-byte hex (see cpp note on order)
    std::vector<std::string> tx_hexes;             // non-coinbase transactions (hex) from getBlock, for block assembly via submitblock
    bool          extra_required_outputs{false};  // true if a required output other than the witness commitment was present
};

// Handle to one bitcoin-node mining IPC connection.
//
// A Cap'n Proto EzRpcClient is affine to the thread that runs its kj event loop,
// so a Client must be built, used and destroyed entirely on ONE thread (in
// mkpool, the Generator's ipcnotify thread); it is not safe to share across
// threads. Failures are reported as return values - no exception ever crosses
// this boundary.
class Client {
public:
    // Connect to the unix socket at socket_path, perform the libmultiprocess
    // handshake and attempt to obtain a Mining capability. Returns a handle on a
    // usable transport, or nullptr if the socket is absent or the loop could not
    // start. A node that is up but not yet ready to mine (still in IBD) still
    // yields a handle: poll ok() / retry reconnect().
    static std::shared_ptr<Client> connect(const std::string& socket_path);

    ~Client();

    // True when the transport is up and a Mining capability is held.
    [[nodiscard]] bool ok() const;

    // Fetch the current chain tip. Returns true and fills out on success; false
    // on failure (a lost connection flags the handle for reconnect()).
    bool get_tip(Tip& out);

    // Block until the tip differs from current_hash (64 hex chars) or
    // timeout_ms elapses. Returns true and fills out on a new tip; false on
    // timeout (normal) or failure (flags the handle for reconnect()).
    bool wait_tip_changed(const std::string& current_hash, double timeout_ms, Tip& out);

    // Re-establish a usable Mining capability after a failure (reconnecting the
    // socket if needed). Returns true once mining is available again.
    bool reconnect();

    // Release the capnp capabilities and transport, on the owning thread, before
    // the handle is dropped. After this the object holds only null members, so it
    // is safe to destroy from any thread even if another thread (e.g. a share
    // worker mid-submit_solution) still holds a reference. Call from the owning
    // thread when retiring a connection.
    void shutdown();

    // Interrupt any in-flight blocking wait (waitTipChanged / createNewBlock via
    // Mining.interrupt, and waitNext via BlockTemplate.interruptWait) so the
    // owning thread returns promptly instead of running out its timeout window.
    // Thread-safe: marshaled onto the loop thread; a no-op if disconnected. Call
    // from another thread (e.g. on shutdown) while the owning thread is blocked.
    void interrupt();

    // ----- template path (used only when ipcTemplate is enabled) -----

    // Create a fresh block template on the node and fill out. The node-side
    // BlockTemplate is retained internally and reachable via out.handle until it
    // is superseded; returns false on failure (flags the handle for reconnect).
    bool get_template(Template& out);

    // Wait, up to timeout_ms, for the template identified by cur_handle to be
    // superseded: either the mempool fees rise by at least fee_threshold sats or
    // a new tip arrives. On a new template returns true and fills out (fresh
    // handle); returns false on timeout (caller re-waits) or failure. Must be
    // called from the owning thread.
    bool wait_next(std::uint64_t cur_handle, std::int64_t fee_threshold,
                   double timeout_ms, Template& out);

    // Submit a solved coinbase for the template identified by handle. The node
    // assembles and broadcasts the full block. coinbase is the complete
    // (segwit, witness-carrying) coinbase transaction bytes. Returns true if the
    // call completed and sets accepted (true also means "already known", which
    // is success); false on transport failure or an unknown/expired handle.
    bool submit_solution(std::uint64_t handle, std::uint32_t version,
                         std::uint32_t timestamp, std::uint32_t nonce,
                         const std::vector<std::uint8_t>& coinbase, bool& accepted);

    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;

private:
    Client();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace mkpool::ipc

