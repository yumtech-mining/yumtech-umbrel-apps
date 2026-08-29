import tempfile
import unittest
from pathlib import Path

from yumtech_dashboard.httpd import make_server
from yumtech_dashboard.storage import Storage


class FakeSettings:
    host = "127.0.0.1"
    port = 0
    basic_auth_user = ""
    basic_auth_password = ""
    static_dir = Path(__file__).resolve().parents[1] / "yumtech_dashboard" / "static"


class FakeService:
    settings = FakeSettings()

    def overview(self):
        return {"online": True}


class HttpTests(unittest.TestCase):
    def test_server_binds_ephemeral_port(self):
        server = make_server(FakeService())
        try:
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
