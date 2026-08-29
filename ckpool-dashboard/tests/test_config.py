import tempfile
import unittest
from pathlib import Path

from yumtech_dashboard.config import first_json_object, read_ckpool_config


class ConfigTests(unittest.TestCase):
    def test_first_object_allows_trailing_comments(self):
        value = first_json_object('{"serverurl":["0.0.0.0:3333"],"note":"} ok"}\n# comment')
        self.assertEqual(value["serverurl"][0], "0.0.0.0:3333")
        self.assertEqual(value["note"], "} ok")

    def test_read_ckpool_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ckpool.conf"
            path.write_text('{"startdiff":16384}\n// generated', encoding="utf-8")
            self.assertEqual(read_ckpool_config(path)["startdiff"], 16384)


if __name__ == "__main__":
    unittest.main()
