// SPDX-License-Identifier: GPL-3.0

#include <catch2/catch_test_macros.hpp>
#include "config.hpp"

TEST_CASE("Bitcoin mining IPC configuration is optional", "[config][ipc]")
{
    const auto coin = mkpool::Config::parseCoin(nlohmann::json::object());
    CHECK(coin.ipcSocket.empty());
    CHECK_FALSE(coin.ipcTemplate);
    CHECK(coin.ipcFeeThreshold == 0);
}

TEST_CASE("Bitcoin mining IPC configuration is parsed", "[config][ipc]")
{
    const auto coin = mkpool::Config::parseCoin({
        {"ipc", {
            {"socket", "/run/bitcoin-ipc/node.sock"},
            {"template", true},
            {"feeThreshold", 25000},
        }},
    });

    CHECK(coin.ipcSocket == "/run/bitcoin-ipc/node.sock");
    CHECK(coin.ipcTemplate);
    CHECK(coin.ipcFeeThreshold == 25000);
}
