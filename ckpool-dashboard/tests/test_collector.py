import tempfile
import unittest
from pathlib import Path

from yumtech_dashboard.collector import LogCollector, parse_difficulty, parse_line, sv2_public_identity
from yumtech_dashboard.storage import Storage


class CollectorTests(unittest.TestCase):
    def test_difficulty_suffixes(self):
        self.assertEqual(parse_difficulty("23.5M"), 23_500_000)
        self.assertEqual(parse_difficulty("1.2G"), 1_200_000_000)

    def test_realistic_share_line(self):
        event = parse_line(
            "[2026-08-29 12:10:11.123] Accepted client 42 share diff 23.5M/16384/125.8T: "
            "0000000000000000000abc"
        )
        self.assertEqual(event["kind"], "share")
        self.assertTrue(event["accepted"])
        self.assertEqual(event["client_id"], "42")
        self.assertEqual(event["share_difficulty"], 23_500_000)

    def test_invalid_share_and_sv2_public_key(self):
        event = parse_line("[2026-08-29 12:10:11] Rejected client 42 invalid share invalid nonce2")
        self.assertFalse(event["accepted"])
        self.assertEqual(event["reason"], "invalid nonce2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ckpool.log"
            key = "9WZx1kZcP5LQ6nKp8Ya3bT7uV2rS4mN6qHjEeFfGgDdC"
            path.write_text(f"SV2 authority URL path (<host>:<port>/{key})\n")
            self.assertEqual(sv2_public_identity(path)[0], key)

    def test_authorization_share_block_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Storage(Path(directory) / "dashboard.db")
            collector = LogCollector(
                Path(directory) / "ckpool.log",
                db,
                lambda height, worker, when: {
                    "height": height,
                    "block_hash": "00abc",
                    "worker_name": worker,
                    "btc_address": worker.split(".")[0],
                    "reward_value": 312_500_000,
                    "round_effort": 0,
                    "net_difficulty": 1000,
                    "found_at": when,
                },
            )
            collector.process_line(
                "[2026-08-29 12:10:10] Authorised client 42 192.0.2.4 worker bc1qexample.s19 as user bc1qexample"
            )
            collector.process_line(
                "[2026-08-29 12:10:11] Accepted client 42 share diff 1.2G/16384/125T: 0000000000abc"
            )
            collector.process_line(
                "[2026-08-29 12:10:12] Solved and confirmed block 999999 by bc1qexample.s19 on SV1"
            )
            collector.process_line(
                "[2026-08-29 12:10:12] Block solved after 1.2G shares at 0.001% diff"
            )
            shares = db.shares()
            blocks = db.blocks()
            self.assertEqual(shares[0]["btc_address"], "bc1qexample")
            self.assertTrue(shares[0]["block_found"])
            self.assertEqual(blocks[0]["height"], 999999)
            self.assertEqual(blocks[0]["round_effort"], 1_200_000_000)

    def test_sv2_effort_can_arrive_before_block_line(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Storage(Path(directory) / "dashboard.db")
            collector = LogCollector(
                Path(directory) / "ckpool.log", db,
                lambda height, worker, when: {"height": height, "worker_name": worker, "found_at": when},
            )
            collector.process_line("[2026-08-29 12:10:11] Block solved after 500M shares at 0.1% diff")
            collector.process_line("[2026-08-29 12:10:12] Block 999999 solved by bc1qexample.s19 accepted on SV2/JD")
            self.assertEqual(db.blocks()[0]["round_effort"], 500_000_000)


if __name__ == "__main__":
    unittest.main()
