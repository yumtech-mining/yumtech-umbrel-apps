# Copyright (c) 2019-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Minimal, mkpool-authored subset of libmultiprocess's include/mp/proxy.capnp.
# We do not depend on libmultiprocess itself; the mining IPC shim hand-rolls the
# handshake on capnp-rpc. This file exists only so that common.capnp, mining.capnp
# and init.capnp parse, and so the ThreadMap / Thread / Context wire types used by
# every Mining call are available to the generated stubs.
#
# The @fileId, the interface/struct NAMES and the method/field ORDINALS are kept
# verbatim from upstream so capnpc derives the exact same wire type ids that the
# bitcoin-node server (which does use libmultiprocess) expects. The annotation ids
# are compile-time only and need not match upstream, so they are left implicit.

@0xcc316e3f71a040fb;

using Cxx = import "/capnp/c++.capnp";
$Cxx.namespace("mp");

annotation include(file) :Text;
annotation includeTypes(file) :Text;
annotation wrap(struct, interface) :Text;
annotation count(param, struct, interface) :Int32;
annotation exception(param) :Text;
annotation name(field, method) :Text;
annotation skip(field) :Void;

interface ThreadMap $count(0) {
    makeThread @0 (name :Text) -> (result :Thread);
    makePool @1 (count :UInt32) -> ();
}

interface Thread {
    getName @0 () -> (result :Text);
}

struct Context $count(0) {
    thread @0 :Thread;
    callbackThread @1 :Thread;
}

