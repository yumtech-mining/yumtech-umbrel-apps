import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from yumtech_dashboard.ckpool import CkpoolError
from yumtech_dashboard.service import DashboardService
from yumtech_dashboard.statusfiles import FRESH_SECONDS, StatusFiles, hashrate, read_pool_status


class StatsOnlyServer:
    """Actual Unix socket: upstream stats responds; API stubs close silently."""

    def __init__(self, path):
        self.calls = []
        self.clients = 2
        self.stop = threading.Event()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(path))
        self.socket.listen(8)
        self.socket.settimeout(0.1)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    @staticmethod
    def read_exact(connection, count):
        result = b""
        while len(result) < count:
            part = connection.recv(count - len(result))
            if not part:
                raise ValueError("incomplete test request")
            result += part
        return result

    def run(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                size = struct.unpack("<I", self.read_exact(connection, 4))[0]
                command = self.read_exact(connection, size).decode()
                self.calls.append(command)
                if command == "stats":
                    payload = json.dumps({"clients": {"count": self.clients}, "workbases": {"count": 1}}).encode()
                    frame = struct.pack("<I", len(payload)) + payload
                    connection.sendall(frame[:2])
                    connection.sendall(frame[2:])

    def close(self):
        self.stop.set()
        self.socket.close()
        self.thread.join(timeout=1)


class StatsOnlyTransport:
    """Byte-level simulation for sandboxes that prohibit Unix socket creation."""
    def __init__(self):
        self.calls = []
        self.clients = 2

    def socket(self, *_args):
        parent = self
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def settimeout(self, _seconds): pass
            def connect(self, _path): pass
            def sendall(self, data):
                size = struct.unpack("<I", data[:4])[0]
                command = data[4:4 + size].decode()
                parent.calls.append(command)
                self.buffer = b""
                if command == "stats":
                    payload = json.dumps({"clients": {"count": parent.clients}, "workbases": {"count": 1}}).encode()
                    self.buffer = struct.pack("<I", len(payload)) + payload
            def recv(self, count):
                result = self.buffer[:min(count, 3)]
                self.buffer = self.buffer[len(result):]
                return result
        return Connection()


class StatusFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.pool = self.root / "pool" / "pool.status"
        self.pool.parent.mkdir()
        self.users = self.root / "users"
        self.users.mkdir()
        self.now = time.time()
        self.settings = SimpleNamespace(
            state_dir=self.root / "state", socket_path=self.root / "stratifier", log_path=self.root / "ckpool.log",
            users_dir=self.users, retention_days=30, rpc_url="http://127.0.0.1:8332", rpc_user="u",
            rpc_password="p", rpc_timeout=1, config={}, sv1_servers=1, sv1_port=3333, sv2_port=3336,
        )
        self.write_pool()
        self.write_user()

    def write_pool(self, when=None, workers=2):
        rows = [
            {"runtime": 3600, "lastupdate": self.now if when is None else when,
             "Users": 1, "Workers": workers, "Idle": 0, "Disconnected": 5},
            {"hashrate1m": "142T", "hashrate5m": "140T", "hashrate1hr": "139T"},
            {"diff": 0.0, "accepted": 123456789, "rejected": 10, "bestshare": 344372893, "SPS1m": 2.1},
            {"sv2": {"clients": 0}},
        ]
        self.pool.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    def write_user(self):
        # Mirrors statsupdate: username is the filename, `workers` is a count,
        # `worker` is the array, and `shares` measures diff, not submissions.
        self.user = self.users / "bc1qexample"
        self.user.write_text(json.dumps({
            "hashrate1m": "142T", "hashrate5m": "140T", "workers": 2,
            "lastshare": self.now - 5, "bestever": 344372893.05599135,
            "worker": [
                {"workername": "bc1qexample.s19", "hashrate1m": "137T", "hashrate5m": "135T",
                 "lastshare": self.now - 5, "bestever": 344372893.05599135, "shares": 983040},
                {"workername": "bc1qexample.nerd", "hashrate1m": "5T", "hashrate5m": "5T",
                 "lastshare": self.now - 10, "bestshare": 1200000, "shares": 32768},
                {"workername": "bc1qexample.old", "hashrate1m": "1T", "hashrate5m": "2T",
                 "lastshare": self.now - 3600, "bestever": 23, "shares": 456},
            ],
        }))

    def service(self):
        service = DashboardService(self.settings)
        service.rpc = SimpleNamespace(node_data=lambda: {"online": True, "blocks": 964706, "difficulty": 100000000000000})
        return service

    def live_server(self):
        server = StatsOnlyTransport()
        patcher = mock.patch("yumtech_dashboard.ckpool.socket.socket", side_effect=server.socket)
        patcher.start()
        self.addCleanup(patcher.stop)
        return server

    def test_hashrate_units_and_invalid_values(self):
        for value, expected in [("142T", 142e12), ("5.47T", 5.47e12), ("1.2G", 1.2e9),
                                ("123k", 123000), ("10", 10), (0, 0), ("2.5 TH/s", 2.5e12),
                                ("NaN", 0), ("-10T", 0), ("1e999", 0)]:
            self.assertEqual(hashrate(value), expected)

    def test_real_upstream_json_lines(self):
        raw = read_pool_status(self.pool)
        self.assertEqual(raw["runtime"], 3600)
        self.assertEqual(raw["accepted"], 123456789)
        self.assertEqual(raw["Workers"], 2)
        self.assertNotIn("sv2", raw)

    def test_stats_only_transport_restores_pool_and_workers(self):
        server = self.live_server()
        service = self.service()
        overview = service.overview()
        miners = service.miners()
        self.assertTrue(overview["online"])
        self.assertTrue(overview["metrics_available"])
        self.assertEqual(overview["data_source"], "status-files")
        self.assertEqual(overview["hashrate_1m"], 142e12)
        self.assertEqual(overview["hashrate_5m"], 140e12)
        self.assertEqual(overview["workers"], 2)
        self.assertEqual(overview["connections"], 2)
        self.assertGreaterEqual(overview["uptime_seconds"], 3600)
        self.assertAlmostEqual(overview["best_share"], 344372893.05599135)
        self.assertEqual([miner["worker_name"] for miner in miners], ["s19", "nerd"])
        self.assertEqual(miners[0]["btc_address"], "bc1qexample")
        self.assertEqual(miners[0]["hashrate"], 137e12)
        self.assertIsNone(miners[0]["connections"])
        self.assertIsNone(miners[0]["difficulty"])
        self.assertIsNone(miners[0]["shares_accepted"])
        self.assertEqual(miners[0]["accepted_difficulty"], 983040)
        self.assertEqual(miners[0]["status_source"], "recent-share")
        self.assertAlmostEqual(service.analytics()["round_effort_pct"], 123456789 / 1e14 * 100)
        self.assertEqual(service.storage.history(1)[0]["hashrate"], 142e12)
        service._pool(force=True)
        self.assertEqual(server.calls.count("clients"), 1)
        self.assertEqual(server.calls.count("poolstats"), 1)
        self.assertNotIn("users", server.calls)

    def test_offline_socket_does_not_reuse_file_as_online(self):
        service = self.service()
        with mock.patch("yumtech_dashboard.ckpool.socket.socket", side_effect=PermissionError("denied")):
            overview = service.overview()
        self.assertFalse(overview["online"])
        self.assertIsNone(overview["hashrate_1m"])
        self.assertEqual(service.miners(), [])
        self.assertGreater(overview["best_share"], 344e6)
        self.assertEqual(service.storage.history(1), [])

    def test_live_socket_stale_files_are_unavailable_not_zero(self):
        self.live_server()
        self.write_pool(self.now - FRESH_SECONDS - 10)
        os.utime(self.user, (self.now - 1000, self.now - 1000))
        service = self.service()
        overview = service.overview()
        self.assertTrue(overview["online"])
        self.assertFalse(overview["metrics_available"])
        self.assertIsNone(overview["hashrate_1m"])
        self.assertIsNone(overview["uptime_seconds"])
        self.assertIsNone(service.analytics()["round_effort_pct"])
        self.assertEqual(service.miners(), [])
        self.assertEqual(service.storage.history(1), [])

    def test_zero_live_clients_hides_recent_workers(self):
        server = self.live_server()
        server.clients = 0
        service = self.service()
        self.assertEqual(service.miners(), [])
        self.assertEqual(service.overview()["connections"], 0)
        self.assertEqual(service.overview()["workers"], 0)

    def test_partial_write_uses_last_good_snapshot_but_expires(self):
        files = StatusFiles(self.pool, self.users)
        self.assertTrue(files.pool()["fresh"])
        self.pool.write_text('{"runtime":')
        self.assertEqual(files.pool()["hashrate1m"], "142T")
        with mock.patch("yumtech_dashboard.statusfiles.time.time", return_value=self.now + FRESH_SECONDS + 1):
            self.assertFalse(files.pool()["fresh"])

    def test_worker_partial_write_keeps_original_freshness(self):
        files = StatusFiles(self.pool, self.users)
        self.assertEqual(len(files.users()["workers"]), 3)
        self.user.write_text('{"worker":')
        with mock.patch("yumtech_dashboard.statusfiles.time.time", return_value=self.now + 6):
            self.assertEqual(len(files.users()["workers"]), 3)
        self.assertLess(files.users()["workers"]["bc1qexample.s19"]["updated_at"], self.now + 1)

    def test_one_optional_api_failure_does_not_drop_other_metrics(self):
        from test_service import FakeCkpool
        service = self.service()
        service.ckpool = FakeCkpool()
        service.ckpool.uptime = mock.Mock(side_effect=CkpoolError("stub"))
        overview = service.overview()
        self.assertTrue(overview["online"])
        self.assertEqual(overview["data_source"], "socket-api")
        self.assertEqual(overview["hashrate_1m"], 2 * 2**32)
        self.assertEqual(len(service.miners()), 1)

    def test_update_preserves_existing_shares_and_log_offsets(self):
        self.live_server()
        old = self.service()
        old.storage.set_log_state("old-log", 123, 456)
        old.storage.insert_share({"event_key": "unchanged", "created_at": self.now,
                                  "accepted": True, "share_difficulty": 999999999})
        new = self.service()
        self.assertEqual(new.storage.log_state("old-log"), (123, 456))
        self.assertEqual(len(new.storage.shares()), 1)
        self.assertEqual(new.overview()["best_share"], 999999999)

    @unittest.skipUnless(os.environ.get("YUMTECH_TEST_UNIX_SOCKETS") == "1", "real Unix socket test runs in CI")
    def test_real_unix_socket_matches_upstream_stub_behavior(self):
        server = StatsOnlyServer(self.settings.socket_path)
        self.addCleanup(server.close)
        service = self.service()
        overview = service.overview()
        self.assertTrue(overview["online"])
        self.assertEqual(overview["data_source"], "status-files")
        self.assertEqual(overview["hashrate_1m"], 142e12)
        self.assertEqual(len(service.miners()), 2)
        self.assertIn("clients", server.calls)


if __name__ == "__main__":
    unittest.main()
