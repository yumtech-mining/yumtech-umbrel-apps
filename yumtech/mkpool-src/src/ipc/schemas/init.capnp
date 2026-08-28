# Copyright (c) 2024-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# mkpool-authored trimmed copy of Bitcoin Core's src/ipc/capnp/init.capnp.
# The upstream Init interface exposes makeChain / makeNode / makeWalletLoader etc.,
# each pulling in a large schema we do not use. We keep only the two methods the
# mining shim invokes (construct, makeMining) plus placeholder declarations for the
# intervening ordinals so makeMining stays at @3. The @fileId and the "Init" name
# are preserved so capnpc derives the same interface wire id the server expects;
# the placeholder methods are never invoked, so their signatures are irrelevant to
# the wire.

@0xf2c5cfa319406aa6;

using Cxx = import "/capnp/c++.capnp";
$Cxx.namespace("ipc::capnp::messages");

using Proxy = import "/mp/proxy.capnp";
using Mining = import "mining.capnp";
$Proxy.include("interfaces/init.h");
$Proxy.includeTypes("ipc/capnp/init-types.h");

interface Init $Proxy.wrap("interfaces::Init") {
    construct @0 (threadMap :Proxy.ThreadMap) -> (threadMap :Proxy.ThreadMap);
    makeEcho @1 (context :Proxy.Context) -> (result :Void);
    makeMiningOld2 @2 () -> ();
    makeMining @3 (context :Proxy.Context) -> (result :Mining.Mining);
}

