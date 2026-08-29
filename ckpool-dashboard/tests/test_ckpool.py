import json
import struct
import unittest
from unittest import mock

from yumtech_dashboard.ckpool import CkpoolClient


class CkpoolSocketTests(unittest.TestCase):
    def test_length_prefixed_poolstats(self):
        payload = json.dumps({"dsps1": 42, "accepted": 100}).encode()

        class FakeSocket:
            def __init__(self):
                self.buffer = bytearray(struct.pack("<I", len(payload)) + payload)
                self.sent = b""
                self.connected = ""

            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def settimeout(self, _timeout): return None
            def connect(self, path): self.connected = path
            def sendall(self, value): self.sent += value
            def recv(self, length):
                value = bytes(self.buffer[:length])
                del self.buffer[:length]
                return value

        fake = FakeSocket()
        with mock.patch("yumtech_dashboard.ckpool.socket.socket", return_value=fake):
            result = CkpoolClient("/tmp/ckpool/stratifier").poolstats()

        size = struct.unpack("<I", fake.sent[:4])[0]
        self.assertEqual(fake.sent[4 : 4 + size], b"poolstats")
        self.assertEqual(fake.connected, "/tmp/ckpool/stratifier")
        self.assertEqual(result["dsps1"], 42)
        self.assertEqual(result["accepted"], 100)


if __name__ == "__main__":
    unittest.main()
