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
// File:        ipc_mining.cpp
// Description: Bitcoin Core mining IPC (Cap'n Proto) client implementation.
// Created:     2026-07-20
// Project:     mkpool - Modern Multi-Coin Solo Mining Pool
//
// Transport: the bitcoin-node mining socket speaks Cap'n Proto RPC using the
// libmultiprocess conventions. We talk to it directly with capnp's EzRpcClient
// and the generated stubs, performing the libmultiprocess handshake by hand:
// exchange thread maps via Init.construct(), then supply a Proxy.Context
// {thread, callbackThread} on every Mining call. This avoids a build dependency
// on libmultiprocess itself; only capnp-rpc is required.
//
// Threading: an EzRpcClient's kj event loop is affine to the thread that
// constructs it, and every call must be issued from that thread. We therefore
// run the loop on one dedicated internal thread and marshal each public call
// onto it via a task queue, blocking the caller until it completes. Calls
// serialize (a long waitTipChanged occupies the loop until it returns), which
// matches the single-outstanding-call usage the notifier drives. This design
// generalises cleanly to the cross-thread template path added later.

#include "ipc_mining.hpp"

#ifdef HAVE_CAPNP

#include <capnp/ez-rpc.h>
#include <kj/array.h>
#include <kj/async.h>
#include <kj/async-io.h>
#include <kj/common.h>
#include <kj/exception.h>
#include <kj/memory.h>
#include <kj/time.h>

#include "init.capnp.h"
#include "mining.capnp.h"
#include "common.capnp.h"
#include "mp/proxy.capnp.h"

#include <atomic>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace mkpool::ipc {

// Leading :: forces global scope: inside namespace mkpool::ipc the bare name
// "ipc" would otherwise resolve to this namespace, not the generated
// ::ipc::capnp::messages. Hoisted to namespace scope so both the anonymous-
// namespace helpers and Client::Impl below can see them.
using ::ipc::capnp::messages::Init;
using ::ipc::capnp::messages::Mining;
using ::ipc::capnp::messages::BlockTemplate;
using ::ipc::capnp::messages::BlockRef;
using ::ipc::capnp::messages::CoinbaseTx;

namespace {

const char* const kHex = "0123456789abcdef";

// Raw bytes -> lowercase hex, preserving byte order.
std::string bytes_to_hex(kj::ArrayPtr<const kj::byte> b)
{
    std::string out;
    out.resize(b.size() * 2);
    for (size_t i = 0; i < b.size(); ++i) {
        out[i * 2]     = kHex[b[i] >> 4];
        out[i * 2 + 1] = kHex[b[i] & 0x0f];
    }
    return out;
}

std::uint32_t read_le32(kj::ArrayPtr<const kj::byte> b, size_t off)
{
    return static_cast<std::uint32_t>(b[off]) |
           (static_cast<std::uint32_t>(b[off + 1]) << 8) |
           (static_cast<std::uint32_t>(b[off + 2]) << 16) |
           (static_cast<std::uint32_t>(b[off + 3]) << 24);
}

// Serialized nBits is little-endian in the header; the compact form miners see
// (and mkpool stores) is the big-endian 8-char hex, i.e. the reversed bytes.
std::string bits_le_to_compact_hex(kj::ArrayPtr<const kj::byte> hdr)
{
    std::string out;
    out.resize(8);
    for (int i = 0; i < 4; ++i) {
        const kj::byte b = hdr[72 + (3 - i)];
        out[i * 2]     = kHex[b >> 4];
        out[i * 2 + 1] = kHex[b & 0x0f];
    }
    return out;
}

// A required coinbase output is a serialized CTxOut: 8-byte value (LE) + varint
// script length + scriptPubKey. Extract the scriptPubKey hex; return false on a
// malformed buffer. The segwit commitment output has a scriptPubKey beginning
// 6a24aa21a9ed (OP_RETURN, 36-byte push, commitment header).
bool parse_txout_script(kj::ArrayPtr<const kj::byte> out, std::string& script_hex)
{
    if (out.size() < 9)
        return false;
    size_t p = 8;
    const kj::byte v = out[p++];
    std::uint64_t len = v;
    if (v == 0xfd) { if (out.size() < p + 2) return false; len = out[p] | (out[p + 1] << 8); p += 2; }
    else if (v == 0xfe || v == 0xff) return false; // scripts this long are not expected here
    if (out.size() < p + len)
        return false;
    script_hex = bytes_to_hex(out.slice(p, p + len));
    return true;
}

bool is_witness_commitment(const std::string& script_hex)
{
    return script_hex.size() >= 12 && script_hex.compare(0, 12, "6a24aa21a9ed") == 0;
}

// Read a Bitcoin varint at *p (bounded by end); advance *p. Returns false on
// truncation or a 64-bit-wide value we never expect in a block.
bool read_varint(const kj::byte*& p, const kj::byte* end, std::uint64_t& out)
{
    if (p >= end) return false;
    const kj::byte v = *p++;
    if (v < 0xfd) { out = v; return true; }
    int n = (v == 0xfd) ? 2 : (v == 0xfe) ? 4 : 8;
    if (end - p < n) return false;
    out = 0;
    for (int i = 0; i < n; ++i) out |= static_cast<std::uint64_t>(*p++) << (8 * i);
    return true;
}

// Advance *p past one serialized transaction (segwit-aware). Returns false on a
// malformed/truncated buffer.
bool skip_tx(const kj::byte*& p, const kj::byte* end)
{
    if (end - p < 4) return false;
    p += 4; // version
    bool segwit = false;
    if (p + 2 <= end && p[0] == 0x00 && p[1] == 0x01) { segwit = true; p += 2; }
    std::uint64_t nin = 0;
    if (!read_varint(p, end, nin)) return false;
    for (std::uint64_t i = 0; i < nin; ++i) {
        if (end - p < 36) return false;
        p += 36; // prevout
        std::uint64_t slen = 0;
        if (!read_varint(p, end, slen)) return false;
        if (static_cast<std::uint64_t>(end - p) < slen + 4) return false;
        p += slen + 4; // script + sequence
    }
    std::uint64_t nout = 0;
    if (!read_varint(p, end, nout)) return false;
    for (std::uint64_t i = 0; i < nout; ++i) {
        if (end - p < 8) return false;
        p += 8; // value
        std::uint64_t slen = 0;
        if (!read_varint(p, end, slen)) return false;
        if (static_cast<std::uint64_t>(end - p) < slen) return false;
        p += slen;
    }
    if (segwit) {
        for (std::uint64_t i = 0; i < nin; ++i) {
            std::uint64_t items = 0;
            if (!read_varint(p, end, items)) return false;
            for (std::uint64_t j = 0; j < items; ++j) {
                std::uint64_t ilen = 0;
                if (!read_varint(p, end, ilen)) return false;
                if (static_cast<std::uint64_t>(end - p) < ilen) return false;
                p += ilen;
            }
        }
    }
    if (end - p < 4) return false;
    p += 4; // locktime
    return true;
}

// Split a serialized block (from BlockTemplate.getBlock) into its non-coinbase
// transaction hexes. tx[0] is the node's dummy coinbase and is skipped; mkpool
// builds its own coinbase. Returns false on a malformed buffer.
bool split_block_txns(kj::ArrayPtr<const kj::byte> block, std::vector<std::string>& out)
{
    const kj::byte* p = block.begin();
    const kj::byte* end = block.end();
    if (end - p < 80) return false;
    p += 80; // header
    std::uint64_t ntx = 0;
    if (!read_varint(p, end, ntx)) return false;
    if (ntx == 0) return true;
    if (!skip_tx(p, end)) return false; // skip the dummy coinbase (tx[0])
    out.reserve(static_cast<size_t>(ntx - 1));
    for (std::uint64_t i = 1; i < ntx; ++i) {
        const kj::byte* start = p;
        if (!skip_tx(p, end)) return false;
        out.push_back(bytes_to_hex(kj::arrayPtr(start, static_cast<size_t>(p - start))));
    }
    return true;
}

// 32 raw hash bytes (node/internal order) -> 64-char big-endian display hex,
// the reversed form miners and block explorers show.
std::string hash_to_display_hex(kj::ArrayPtr<const kj::byte> hash)
{
    std::string out;
    if (hash.size() != 32)
        return out;
    out.resize(64);
    for (size_t i = 0; i < 32; ++i) {
        const kj::byte b = hash[31 - i];
        out[i * 2]     = kHex[b >> 4];
        out[i * 2 + 1] = kHex[b & 0x0f];
    }
    return out;
}

int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// 64-char big-endian display hex -> 32 raw bytes in node/internal order.
bool display_hex_to_hash(const std::string& hex, kj::byte out[32])
{
    if (hex.size() != 64)
        return false;
    for (size_t i = 0; i < 32; ++i) {
        const int hi = hex_nibble(hex[i * 2]);
        const int lo = hex_nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0)
            return false;
        out[31 - i] = static_cast<kj::byte>((hi << 4) | lo);
    }
    return true;
}

bool fill_tip(BlockRef::Reader ref, Tip& out)
{
    auto hash = ref.getHash();
    if (hash.size() != 32)
        return false;
    out.hash = hash_to_display_hex(hash);
    out.height = ref.getHeight();
    return true;
}

// Minimal server capabilities satisfying the libmultiprocess handshake. The
// node needs a valid Thread handle in every Context; we serve a ThreadMap so it
// can create callback thread handles routed back to us. We do not run any real
// callbacks, so these are intentionally trivial.
//
// capnp's generated mp::*::Server bases have non-virtual destructors, but capnp
// only ever owns and destroys these through their exact kj::Own<T> type, never
// through a base pointer, so the -Wnon-virtual-dtor risk does not apply here.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wnon-virtual-dtor"
class ThreadServer final : public mp::Thread::Server {
public:
    explicit ThreadServer(kj::StringPtr name) : name_(kj::str(name)) {}
    kj::Promise<void> getName(GetNameContext context) override
    {
        context.getResults().setResult(name_);
        return kj::READY_NOW;
    }
private:
    kj::String name_;
};

class ThreadMapServer final : public mp::ThreadMap::Server {
public:
    kj::Promise<void> makeThread(MakeThreadContext context) override
    {
        auto name = context.getParams().getName();
        context.getResults().setResult(mp::Thread::Client(kj::heap<ThreadServer>(name)));
        return kj::READY_NOW;
    }
};
#pragma GCC diagnostic pop

} // namespace

// ---------------------------------------------------------------------------

struct Client::Impl {
    std::string socket_path;

    // Owned and used entirely on the caller's thread: an EzRpcClient's kj event
    // loop is affine to the thread that constructs it, so this Client is built,
    // used and destroyed from one thread (the Generator's ipcnotify thread). No
    // cross-thread marshaling; that is why kj sees a live event loop on every
    // call. Destruction order is reverse-declaration, so the capnp capabilities
    // below are released before ez while the loop is still current.
    std::unique_ptr<capnp::EzRpcClient> ez;
    kj::WaitScope*        ws{nullptr};
    Init::Client          init{nullptr};
    Mining::Client        mining{nullptr};
    mp::ThreadMap::Client client_map{nullptr};    // served by us
    mp::ThreadMap::Client server_map{nullptr};    // returned by construct()
    mp::Thread::Client    server_thread{nullptr}; // execution thread on the node
    mp::Thread::Client    server_thread_submit{nullptr}; // dedicated node thread for submitSolution
    mp::Thread::Client    client_thread{nullptr}; // our callback thread
    std::atomic<bool>     have_mining{false};     // read lock-free by ok()

    // Executor for this connection's kj event loop, captured on the owning
    // thread. Lets submit_solution() marshal onto the loop thread from the share
    // worker thread (the one cross-thread caller); every other method runs on
    // the owning thread directly. Null while disconnected.
    std::atomic<const kj::Executor*> executor{nullptr};

    // Handle of the template currently blocked in waitNext (0 if none). Written
    // by the owning thread around the wait, read by interrupt() from another
    // thread to target the right BlockTemplate.interruptWait.
    std::atomic<std::uint64_t> waiting_handle{0};

    // Retained node-side BlockTemplate capabilities, keyed by handle, kept until
    // superseded so a winning share can submitSolution against its job. Bounded
    // well above the job window.
    std::map<std::uint64_t, BlockTemplate::Client> templates;
    std::uint64_t         next_handle{1};
    static constexpr size_t kMaxTemplates = 96;

    // Build the transport and perform the libmultiprocess handshake, leaving a
    // usable Mining capability. Returns false (tearing the transport down) on
    // failure. Runs on the owning thread.
    bool build_transport()
    {
        try {
            // kj parses "unix:/path" as a Unix domain socket; a bare path would
            // be misread as host:port. The node is reached with a matching
            // bitcoin-node -ipcbind=unix:/path.
            const std::string addr = "unix:" + socket_path;
            ez = std::make_unique<capnp::EzRpcClient>(kj::StringPtr(addr.c_str()));
            ws = &ez->getWaitScope();
            init = ez->getMain<Init>();
            do_handshake();
            // Capture the loop's executor so submit_solution() can marshal onto
            // this thread from the share worker thread.
            executor.store(&kj::getCurrentThreadExecutor(), std::memory_order_release);
            have_mining = true;
            return true;
        } catch (kj::Exception&) {
            teardown();
            return false;
        }
    }

    // Release the capnp capabilities and the transport in dependency order, on
    // the owning thread (while ez, hence the event loop, is still alive).
    void teardown()
    {
        have_mining = false;
        executor.store(nullptr, std::memory_order_release);
        templates.clear();
        mining = Mining::Client{nullptr};
        server_thread = mp::Thread::Client{nullptr};
        server_thread_submit = mp::Thread::Client{nullptr};
        client_thread = mp::Thread::Client{nullptr};
        server_map = mp::ThreadMap::Client{nullptr};
        client_map = mp::ThreadMap::Client{nullptr};
        init = Init::Client{nullptr};
        ws = nullptr;
        ez.reset();
    }

    void set_ctx(mp::Context::Builder ctx)
    {
        ctx.setThread(server_thread);
        ctx.setCallbackThread(client_thread);
    }

    // Context for submitSolution: runs on a dedicated node-side thread so a found
    // block is processed immediately instead of queuing behind the parked
    // waitNext on the main server_thread (libmultiprocess runs each call on the
    // thread named in its Context; a blocking waitNext holds server_thread for up
    // to its timeout, so sharing it serialised the submit ~2s behind the wait).
    void set_ctx_submit(mp::Context::Builder ctx)
    {
        ctx.setThread(server_thread_submit);
        ctx.setCallbackThread(client_thread);
    }

    // -- on-loop-thread helpers ------------------------------------------------

    bool do_handshake()
    {
        client_map = mp::ThreadMap::Client(kj::heap<ThreadMapServer>());

        auto creq = init.constructRequest();
        creq.setThreadMap(client_map);
        server_map = creq.send().wait(*ws).getThreadMap();

        auto mreq = server_map.makeThreadRequest();
        mreq.setName("mkpool-ipc");
        server_thread = mreq.send().wait(*ws).getResult();

        // Second node-side execution thread used only by submitSolution. The main
        // server_thread is parked inside a blocking waitNext almost continuously;
        // a found-block submit sharing that thread would queue behind the wait.
        auto sreq = server_map.makeThreadRequest();
        sreq.setName("mkpool-ipc-submit");
        server_thread_submit = sreq.send().wait(*ws).getResult();

        client_thread = mp::Thread::Client(kj::heap<ThreadServer>("mkpool-ipc-cb"));

        auto mm = init.makeMiningRequest();
        set_ctx(mm.initContext());
        mining = mm.send().wait(*ws).getResult();
        return true;
    }

    bool do_get_tip(Tip& out)
    {
        if (!have_mining)
            return false;
        try {
            auto req = mining.getTipRequest();
            set_ctx(req.initContext());
            auto res = req.send().wait(*ws);
            if (!res.getHasResult())
                return false;
            return fill_tip(res.getResult(), out);
        } catch (kj::Exception&) {
            have_mining = false;
            return false;
        }
    }

    bool do_wait_tip(const std::string& cur_hex, double timeout_ms, Tip& out)
    {
        if (!have_mining)
            return false;
        kj::byte cur[32];
        if (!display_hex_to_hash(cur_hex, cur))
            return false;
        try {
            auto req = mining.waitTipChangedRequest();
            set_ctx(req.initContext());
            req.setCurrentTip(kj::arrayPtr(cur, 32));
            req.setTimeout(timeout_ms);
            auto res = req.send().wait(*ws);
            Tip t;
            if (!fill_tip(res.getResult(), t))
                return false;
            if (t.hash == cur_hex)   // server returned the same tip: timeout
                return false;
            out = t;
            return true;
        } catch (kj::Exception&) {
            have_mining = false;
            return false;
        }
    }

    bool do_reconnect()
    {
        try {
            // Re-obtain a Mining capability over the existing transport. Used
            // when the node is up but was not yet ready to mine (IBD). A dead
            // transport throws here, and the owner discards this Client and
            // builds a fresh one.
            auto mm = init.makeMiningRequest();
            set_ctx(mm.initContext());
            mining = mm.send().wait(*ws).getResult();
            have_mining = true;
        } catch (kj::Exception&) {
            have_mining = false;
            return false;
        }
        Tip t;
        return do_get_tip(t); // true only once the node reports a tip
    }

    // Read all fields of a BlockTemplate capability into out, retain it under a
    // fresh handle, and evict old ones. Runs on the owning thread and may throw
    // (e.g. a null capability from a waitNext timeout); callers catch.
    bool read_template(BlockTemplate::Client tmpl, Template& out)
    {
        // Height = current tip height + 1. mkpool builds its own BIP34 height
        // push from this, so the value must be correct.
        Tip tip;
        if (!do_get_tip(tip))
            return false;

        // Header: version @0-3 LE, prevhash @4-35 (internal), nTime @68-71 LE,
        // nBits @72-75 LE.
        {
            auto hreq = tmpl.getBlockHeaderRequest();
            set_ctx(hreq.initContext());
            auto hresp = hreq.send().wait(*ws);
            auto hdr = hresp.getResult();
            if (hdr.size() != 80)
                return false;
            out.version  = read_le32(hdr, 0);
            out.curtime  = read_le32(hdr, 68);
            out.bits     = bits_le_to_compact_hex(hdr);
            out.prevhash = hash_to_display_hex(hdr.slice(4, 36));
        }

        // Coinbase fields: reward budget and the required outputs.
        {
            auto creq = tmpl.getCoinbaseTxRequest();
            set_ctx(creq.initContext());
            auto cresp = creq.send().wait(*ws);
            CoinbaseTx::Reader cb = cresp.getResult();
            out.coinbase_value = cb.getBlockRewardRemaining();
            out.witness_commitment.clear();
            out.extra_required_outputs = false;
            for (auto ro : cb.getRequiredOutputs()) {
                std::string script;
                if (!parse_txout_script(ro, script)) {
                    out.extra_required_outputs = true;
                    continue;
                }
                if (is_witness_commitment(script))
                    out.witness_commitment = script;
                else
                    out.extra_required_outputs = true;
            }
        }

        // Precomputed coinbase merkle path: raw-byte hex, node order (verified
        // byte-for-byte against merkle::build_branch_le_hex on testnet).
        {
            auto mreq = tmpl.getCoinbaseMerklePathRequest();
            set_ctx(mreq.initContext());
            auto mresp = mreq.send().wait(*ws);
            auto path = mresp.getResult();
            out.merkle_branch.clear();
            out.merkle_branch.reserve(path.size());
            for (auto node : path)
                out.merkle_branch.push_back(bytes_to_hex(node));
        }

        // Full block (with a dummy coinbase we skip) -> the non-coinbase tx
        // hexes, so the existing submitblock assembly path stays a valid fallback.
        {
            auto breq = tmpl.getBlockRequest();
            set_ctx(breq.initContext());
            auto bresp = breq.send().wait(*ws);
            auto block = bresp.getResult();
            out.tx_hexes.clear();
            if (!split_block_txns(block, out.tx_hexes))
                return false;
        }

        out.height = tip.height + 1;
        out.handle = next_handle++;
        templates.emplace(out.handle, kj::mv(tmpl));
        while (templates.size() > kMaxTemplates)
            templates.erase(templates.begin());
        return true;
    }

    bool do_get_template(Template& out)
    {
        if (!have_mining)
            return false;
        try {
            auto cnb = mining.createNewBlockRequest();
            set_ctx(cnb.initContext());
            BlockTemplate::Client tmpl = cnb.send().wait(*ws).getResult();
            return read_template(kj::mv(tmpl), out);
        } catch (kj::Exception&) {
            have_mining = false;
            return false;
        }
    }

    // Wait for the template cur_handle to be superseded (fee rise past
    // fee_threshold, or a new tip), up to timeout_ms. A timeout returns a null
    // capability whose first read throws (kj FAILED) -> reported as false without
    // dropping the connection; only DISCONNECTED clears have_mining so the owner
    // rebuilds.
    bool do_wait_next(std::uint64_t cur_handle, std::int64_t fee_threshold,
                      double timeout_ms, Template& out)
    {
        if (!have_mining)
            return false;
        auto it = templates.find(cur_handle);
        if (it == templates.end())
            return false;
        try {
            auto req = it->second.waitNextRequest();
            set_ctx(req.initContext());
            auto opts = req.initOptions();
            opts.setTimeout(timeout_ms);
            opts.setFeeThreshold(fee_threshold);
            waiting_handle.store(cur_handle, std::memory_order_release);
            auto resp = req.send().wait(*ws);
            waiting_handle.store(0, std::memory_order_release);
            BlockTemplate::Client nt = resp.getResult();
            return read_template(kj::mv(nt), out);
        } catch (kj::Exception& e) {
            waiting_handle.store(0, std::memory_order_release);
            if (e.getType() == kj::Exception::Type::DISCONNECTED)
                have_mining = false;
            return false;
        }
    }

    // Runs on the loop thread (via interrupt()'s executor). Fires Mining.interrupt
    // (unblocks waitTipChanged / createNewBlock) and, if a waitNext is in flight,
    // BlockTemplate.interruptWait on that template. Both requests are dispatched;
    // we return when the first response arrives (the other was still delivered).
    kj::Promise<void> interrupt_on_loop()
    {
        kj::Promise<void> p = have_mining.load()
            ? mining.interruptRequest().send().ignoreResult()
            : kj::Promise<void>(kj::READY_NOW);
        const std::uint64_t h = waiting_handle.load(std::memory_order_acquire);
        if (h) {
            auto it = templates.find(h);
            if (it != templates.end())
                return p.exclusiveJoin(it->second.interruptWaitRequest().send().ignoreResult());
        }
        return p;
    }

    // Runs on the owning (loop) thread, marshaled there by submit_solution() via
    // the executor. Returns a promise so it never nests a .wait() inside the
    // already-running event loop.
    kj::Promise<bool> submit_on_loop(std::uint64_t handle, std::uint32_t version,
                                     std::uint32_t timestamp, std::uint32_t nonce,
                                     const std::vector<std::uint8_t>& coinbase, bool& accepted)
    {
        auto it = templates.find(handle);
        if (it == templates.end())
            return kj::Promise<bool>(false);
        auto req = it->second.submitSolutionRequest();
        set_ctx_submit(req.initContext());
        req.setVersion(version);
        req.setTimestamp(timestamp);
        req.setNonce(nonce);
        req.setCoinbase(kj::arrayPtr(
            reinterpret_cast<const kj::byte*>(coinbase.data()), coinbase.size()));
        auto submitted = req.send().then([&accepted](auto&& resp) -> bool {
            accepted = resp.getResult();  // ProcessNewBlock: true = valid & accepted
            return true;
        });
        // Bound the wait so an unresponsive node can never tie up the share
        // worker thread on a found block. On timeout we report failure; the
        // caller's submitblock is the guaranteed delivery path regardless.
        return submitted.exclusiveJoin(
            ez->getIoProvider().getTimer().afterDelay(2 * kj::SECONDS)
                .then([]() -> bool { return false; }));
    }
};

// ---------------------------------------------------------------------------

Client::Client() : impl_(std::make_unique<Impl>()) {}

// Impl (its capnp capabilities and the EzRpcClient) is destroyed here, on the
// owning thread, with the event loop still current.
Client::~Client() = default;

std::shared_ptr<Client> Client::connect(const std::string& socket_path)
{
    std::shared_ptr<Client> c(new Client());
    c->impl_->socket_path = socket_path;
    if (!c->impl_->build_transport())
        return nullptr;
    return c;
}

bool Client::ok() const
{
    return impl_->have_mining.load();
}

bool Client::get_tip(Tip& out)
{
    return impl_->do_get_tip(out);
}

bool Client::wait_tip_changed(const std::string& current_hash, double timeout_ms, Tip& out)
{
    return impl_->do_wait_tip(current_hash, timeout_ms, out);
}

bool Client::reconnect()
{
    // Rebuild the transport if it was torn down, otherwise re-obtain Mining.
    if (!impl_->ez)
        return impl_->build_transport();
    return impl_->do_reconnect();
}

void Client::shutdown()
{
    // Owning thread: release capnp + transport now so ~Client is a no-op that
    // can safely run on any thread.
    impl_->teardown();
}

void Client::interrupt()
{
    // Marshal onto the loop thread (which is pumping the blocked owning thread's
    // waitNext/waitTipChanged) to send the interrupt requests. A loop torn down
    // mid-call throws and is ignored.
    const kj::Executor* ex = impl_->executor.load(std::memory_order_acquire);
    if (!ex)
        return;
    try {
        ex->executeSync([this]() -> kj::Promise<void> { return impl_->interrupt_on_loop(); });
    } catch (kj::Exception&) {
    }
}

bool Client::get_template(Template& out)
{
    return impl_->do_get_template(out);
}

bool Client::wait_next(std::uint64_t cur_handle, std::int64_t fee_threshold,
                       double timeout_ms, Template& out)
{
    return impl_->do_wait_next(cur_handle, fee_threshold, timeout_ms, out);
}

bool Client::submit_solution(std::uint64_t handle, std::uint32_t version,
                             std::uint32_t timestamp, std::uint32_t nonce,
                             const std::vector<std::uint8_t>& coinbase, bool& accepted)
{
    // Called from the share worker thread. Marshal onto the connection's loop
    // thread via its executor; executeSync runs submit_on_loop there (as a
    // promise, no nested wait) and blocks us until it resolves. The loop is being
    // pumped by the notify thread's in-flight waitNext, so this runs promptly.
    const kj::Executor* ex = impl_->executor.load(std::memory_order_acquire);
    if (!ex)
        return false;
    try {
        return ex->executeSync([&]() -> kj::Promise<bool> {
            return impl_->submit_on_loop(handle, version, timestamp, nonce, coinbase, accepted);
        });
    } catch (kj::Exception&) {
        return false;
    }
}

} // namespace mkpool::ipc

#else // !HAVE_CAPNP

// Inert fallback so the facade links even in a build without Cap'n Proto. In
// practice CMake only compiles this TU when MKPOOL_ENABLE_IPC=ON, but keeping a
// trivial definition here makes the file self-contained and harmless.
namespace mkpool::ipc {

struct Client::Impl {};
Client::Client() = default;
Client::~Client() = default;
std::shared_ptr<Client> Client::connect(const std::string&) { return nullptr; }
bool Client::ok() const { return false; }
bool Client::get_tip(Tip&) { return false; }
bool Client::wait_tip_changed(const std::string&, double, Tip&) { return false; }
bool Client::reconnect() { return false; }
void Client::shutdown() {}
void Client::interrupt() {}
bool Client::get_template(Template&) { return false; }
bool Client::wait_next(std::uint64_t, std::int64_t, double, Template&) { return false; }
bool Client::submit_solution(std::uint64_t, std::uint32_t, std::uint32_t,
                             std::uint32_t, const std::vector<std::uint8_t>&, bool&) { return false; }

} // namespace mkpool::ipc

#endif // HAVE_CAPNP

