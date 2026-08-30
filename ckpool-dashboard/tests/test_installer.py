import unittest
from pathlib import Path
import tomllib

from yumtech_dashboard import __version__


class InstallerTests(unittest.TestCase):
    def test_update_restarts_only_dashboard_and_preserves_data(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "install.sh").read_text()
        self.assertIn("systemctl restart yumtech-ckpool-dashboard.service", script)
        self.assertNotIn("systemctl enable --now", script)
        self.assertNotIn("systemctl restart ckpool", script)
        self.assertNotIn("systemctl restart bitcoind", script)
        self.assertIn('if [[ ! -f ${ENV_FILE} ]]', script)
        self.assertNotIn("rm -rf /var/lib", script)
        self.assertIn('[[ ${READY} != true ]]', script)
        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        self.assertEqual(version, __version__)


if __name__ == "__main__":
    unittest.main()
