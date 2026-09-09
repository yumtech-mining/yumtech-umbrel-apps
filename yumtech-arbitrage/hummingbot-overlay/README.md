# YUMTECH Hummingbot overlay

This directory contains only the Turkish exchange connectors and the narrowly
scoped privacy/safety changes used by YUMTECH. The engine is built from the
unaltered upstream source revision pinned in `UPSTREAM.lock`; overlays are then
copied on top and the small patches in `patches/` are applied.

`scripts/prepare-hummingbot.sh` verifies the upstream commit before modifying
the worktree. It fails closed if the source or privacy patch no longer matches.

BTCTürk market BUY miktar semantiği `btcturk_order_semantics.py` içinde ayrıca
uyarlanır: Hummingbot'un base miktarı, taze fiyat/ücret/güvenlik payı ve TRY
bakiye doğrulamasından sonra yukarı yuvarlanmış quote miktarına çevrilir. Market
SELL base miktarı olarak kalır; genel connector yolu yanlışlıkla market BUY
göndermemesi için yalnızca limit emir destekler.
