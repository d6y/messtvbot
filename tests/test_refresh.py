import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import importlib

refresh = importlib.import_module("refresh")


class LoadConfigKioskDirTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)
        for key in ("KIOSK_SLACK_TOKEN", "KIOSK_SLACK_CHANNEL", "KIOSK_DIR"):
            os.environ.pop(key, None)
        os.environ["KIOSK_SLACK_TOKEN"] = "xoxb-test"
        os.environ["KIOSK_SLACK_CHANNEL"] = "C1"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_dollar_home_in_kiosk_dir_is_expanded(self):
        os.environ["KIOSK_DIR"] = "$HOME/kiosk-data"
        cfg = refresh.load_config(["refresh.py"])
        self.assertEqual(cfg.kiosk_dir, Path.home() / "kiosk-data")

    def test_tilde_in_kiosk_dir_is_still_expanded(self):
        os.environ["KIOSK_DIR"] = "~/kiosk-data"
        cfg = refresh.load_config(["refresh.py"])
        self.assertEqual(cfg.kiosk_dir, Path.home() / "kiosk-data")

    def test_default_kiosk_dir_is_home(self):
        cfg = refresh.load_config(["refresh.py"])
        self.assertEqual(cfg.kiosk_dir, Path.home() / "kiosk-data")


def _attachment_entry(text="", local_files=None, ts="100.1"):
    return {
        "ts": ts, "kind": "attachment", "text": text, "author": "Jane",
        "posted_at": "2026-08-01T00:00:00+00:00", "local_files": local_files or [],
    }


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.kiosk_dir = self.tmp_dir / "kiosk-data"
        self.kiosk_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_image_with_caption_includes_caption_field(self):
        image_path = self.kiosk_dir / "source" / "slack-100.1.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(b"x")
        entry = _attachment_entry(text="Free pizza today!", local_files=[str(image_path)])
        manifest = refresh.build_manifest([("100.1", entry)], {}, self.kiosk_dir, 8, 30)
        self.assertEqual(manifest["items"][0]["caption"], "Free pizza today!")

    def test_image_without_caption_has_no_caption_field(self):
        image_path = self.kiosk_dir / "source" / "slack-100.1.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(image_path)])
        manifest = refresh.build_manifest([("100.1", entry)], {}, self.kiosk_dir, 8, 30)
        self.assertNotIn("caption", manifest["items"][0])

    def test_pdf_page_never_includes_caption(self):
        pdf_path = self.kiosk_dir / "source" / "slack-100.1.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        page_path = self.kiosk_dir / "rendered" / "slack-100.1" / "page-1.png"
        page_path.parent.mkdir(parents=True)
        page_path.write_bytes(b"x")
        entry = _attachment_entry(text="a caption on a flyer", local_files=[str(pdf_path)])
        manifest = refresh.build_manifest(
            [("100.1", entry)], {"slack-100.1": [page_path]}, self.kiosk_dir, 8, 30
        )
        self.assertNotIn("caption", manifest["items"][0])

    def _make_image(self, name):
        path = self.kiosk_dir / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_multiple_images_without_caption_become_a_grid_of_image_regions(self):
        a = self._make_image("slack-100.5-0.jpg")
        b = self._make_image("slack-100.5-1.png")
        entry = _attachment_entry(text="", local_files=[str(a), str(b)], ts="100.5")
        manifest = refresh.build_manifest([("100.5", entry)], {}, self.kiosk_dir, 8, 30)
        self.assertEqual(len(manifest["items"]), 1)
        item = manifest["items"][0]
        self.assertEqual(item["kind"], "grid")
        self.assertEqual(item["regions"], [
            {"kind": "image", "src": "source/slack-100.5-0.jpg", "name": "slack-100.5-0.jpg"},
            {"kind": "image", "src": "source/slack-100.5-1.png", "name": "slack-100.5-1.png"},
        ])

    def test_multiple_images_with_caption_put_text_region_first(self):
        a = self._make_image("slack-100.6-0.jpg")
        b = self._make_image("slack-100.6-1.png")
        entry = _attachment_entry(text="Team photos!", local_files=[str(a), str(b)], ts="100.6")
        manifest = refresh.build_manifest([("100.6", entry)], {}, self.kiosk_dir, 8, 30)
        item = manifest["items"][0]
        self.assertEqual(item["kind"], "grid")
        self.assertEqual(item["regions"][0], {"kind": "text", "text": "Team photos!"})
        self.assertEqual(len(item["regions"]), 3)

    def test_grid_skips_an_image_not_under_kiosk_dir(self):
        a = self._make_image("slack-100.7-0.jpg")
        outside = Path(tempfile.mkdtemp()) / "slack-100.7-1.png"
        outside.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(a), str(outside)], ts="100.7")
        manifest = refresh.build_manifest([("100.7", entry)], {}, self.kiosk_dir, 8, 30)
        item = manifest["items"][0]
        self.assertEqual(len(item["regions"]), 1)
        self.assertEqual(item["regions"][0]["name"], "slack-100.7-0.jpg")


class CopySiteAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_copy_site_assets_copies_admin_page(self):
        repo_dir = Path(__file__).resolve().parent.parent
        kiosk_dir = self.tmp_dir / "kiosk-data"
        kiosk_dir.mkdir()
        refresh.copy_site_assets(repo_dir, kiosk_dir)
        self.assertTrue((kiosk_dir / "admin" / "index.html").exists())
        self.assertTrue((kiosk_dir / "admin" / "admin.js").exists())


if __name__ == "__main__":
    unittest.main()
