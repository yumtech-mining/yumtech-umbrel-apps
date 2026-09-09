import unittest

from hummingbot.connector.exchange.btcturk.btcturk_signing import generate_signature


class BtcTurkSigningTests(unittest.TestCase):
    def test_generates_expected_signature(self):
        signature = generate_signature(
            api_key="test-key",
            api_secret="dGVzdC1zZWNyZXQ=",
            timestamp_ms=1700000000123,
        )
        self.assertEqual("XORLW3AaT5ikKu+tz7ToTvU+f6jr7ndvb/gZ4aPBlx0=", signature)

    def test_rejects_non_base64_secret(self):
        with self.assertRaisesRegex(ValueError, "valid base64"):
            generate_signature("test-key", "not-valid-base64!", 1700000000123)

