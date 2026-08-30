import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from yumtech_dashboard.service import DIFF_TO_HASHRATE, DashboardService


class FakeCkpool:
    def stats(self): return {"clients": {"count": 1}}
    def poolstats(self): return {"dsps1": 2, "dsps5": 1.5, "accepted": 5000}
    def clients(self):
        return [{
            "id": 42, "user": "bc1qexample", "workername": "bc1qexample.s19",
            "authorised": 1, "subscribed": 1, "idle": 0, "server": 0,
            "diff": 16384, "dsps1": 1, "dsps5": 0.8, "bestdiff": 900,
            "lastshare": 1_800_000_000, "starttime": 1_799_999_000,
            "address": "192.0.2.10", "useragent": "Antminer S19",
        }]
    def workers(self):
        return [{"worker": "bc1qexample.s19", "dsps1": 1, "dsps5": 0.8, "bestdiff": 900, "lastshare": 1_800_000_000}]
    def users(self): return []
    def uptime(self): return 3600


class FakeRpc:
    def node_data(self):
        return {"online": True, "blocks": 999_999, "difficulty": 100_000, "node_name": "Bitcoin Core"}
    def block_hash(self, height): return f"hash-{height}"
    def block_reward_sats(self, _height, _hash=""): return 312_500_000


class ServiceTests(unittest.TestCase):
    def test_live_miners_and_permanent_best_share(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            users = root / "users"
            users.mkdir()
            (users / "bc1qexample").write_text(json.dumps({
                "user": "bc1qexample",
                "bestever": 1_100_000_000,
                "worker": [{"workername": "bc1qexample.s19", "bestever": 1_200_000_000, "shares": 77}],
            }))
            settings = SimpleNamespace(
                state_dir=root / "state", socket_path=root / "stratifier", log_path=root / "ckpool.log",
                users_dir=users, retention_days=30, rpc_url="http://127.0.0.1:8332", rpc_user="u",
                rpc_password="p", rpc_timeout=1, config={"serverurl": ["0.0.0.0:3333"], "sv2url": ["0.0.0.0:3336"]},
                sv1_servers=1, sv1_port=3333, sv2_port=3336,
            )
            service = DashboardService(settings)
            service.ckpool = FakeCkpool()
            service.rpc = FakeRpc()

            miners = service.miners()
            overview = service.overview()
            analytics = service.analytics()

            self.assertEqual(len(miners), 1)
            self.assertEqual(miners[0]["worker_name"], "s19")
            self.assertEqual(miners[0]["btc_address"], "bc1qexample")
            self.assertEqual(miners[0]["best_share_difficulty"], 1_200_000_000)
            self.assertEqual(miners[0]["shares_accepted"], 0)
            self.assertEqual(miners[0]["accepted_difficulty"], 77)
            self.assertEqual(overview["hashrate_1m"], 2 * DIFF_TO_HASHRATE)
            self.assertEqual(overview["template_height"], 1_000_000)
            self.assertAlmostEqual(analytics["round_effort_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
