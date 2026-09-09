# YUMTECH Hummingbot overlay

This directory contains only the Turkish exchange connectors and the narrowly
scoped privacy/safety changes used by YUMTECH. The engine is built from the
unaltered upstream source revision pinned in `UPSTREAM.lock`; overlays are then
copied on top and the small patches in `patches/` are applied.

`scripts/prepare-hummingbot.sh` verifies the upstream commit before modifying
the worktree. It fails closed if the source or privacy patch no longer matches.

