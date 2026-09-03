import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import importlib

masthead_refresh = importlib.import_module("masthead-refresh")


class LoadConfigMastheadDirTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)
        for key in ("MASTHEAD_SLACK_TOKEN", "MASTHEAD_SLACK_CHANNEL", "MASTHEAD_DIR"):
            os.environ.pop(key, None)
        os.environ["MASTHEAD_SLACK_TOKEN"] = "xoxb-test"
        os.environ["MASTHEAD_SLACK_CHANNEL"] = "C1"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_dollar_home_in_masthead_dir_is_expanded(self):
        os.environ["MASTHEAD_DIR"] = "$HOME/masthead-data"
        cfg = masthead_refresh.load_config(["masthead-refresh.py"])
        self.assertEqual(cfg.masthead_dir, Path.home() / "masthead-data")

    def test_tilde_in_masthead_dir_is_still_expanded(self):
        os.environ["MASTHEAD_DIR"] = "~/masthead-data"
        cfg = masthead_refresh.load_config(["masthead-refresh.py"])
        self.assertEqual(cfg.masthead_dir, Path.home() / "masthead-data")

    def test_default_masthead_dir_is_home(self):
        cfg = masthead_refresh.load_config(["masthead-refresh.py"])
        self.assertEqual(cfg.masthead_dir, Path.home() / "masthead-data")


if __name__ == "__main__":
    unittest.main()
