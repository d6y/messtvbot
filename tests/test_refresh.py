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
        for key in ("KIOSK_SLACK_TOKEN", "KIOSK_SLACK_CHANNEL", "KIOSK_DIR", "KIOSK_MAX_IMAGES"):
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

    def test_default_max_images_is_6(self):
        cfg = refresh.load_config(["refresh.py"])
        self.assertEqual(cfg.max_images, 6)

    def test_max_images_is_read_from_env(self):
        os.environ["KIOSK_MAX_IMAGES"] = "3"
        cfg = refresh.load_config(["refresh.py"])
        self.assertEqual(cfg.max_images, 3)


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

    def test_pdf_page_includes_caption_when_present(self):
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
        self.assertEqual(manifest["items"][0]["caption"], "a caption on a flyer")

    def test_pdf_page_has_no_caption_field_when_none_posted(self):
        pdf_path = self.kiosk_dir / "source" / "slack-100.2.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        page_path = self.kiosk_dir / "rendered" / "slack-100.2" / "page-1.png"
        page_path.parent.mkdir(parents=True)
        page_path.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(pdf_path)], ts="100.2")
        manifest = refresh.build_manifest(
            [("100.2", entry)], {"slack-100.2": [page_path]}, self.kiosk_dir, 8, 30
        )
        self.assertNotIn("caption", manifest["items"][0])

    def test_pdf_caption_repeats_on_every_page(self):
        pdf_path = self.kiosk_dir / "source" / "slack-100.3.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        page1 = self.kiosk_dir / "rendered" / "slack-100.3" / "page-1.png"
        page2 = self.kiosk_dir / "rendered" / "slack-100.3" / "page-2.png"
        page1.parent.mkdir(parents=True)
        page1.write_bytes(b"x")
        page2.write_bytes(b"x")
        entry = _attachment_entry(text="Flyer for the summer party", local_files=[str(pdf_path)], ts="100.3")
        manifest = refresh.build_manifest(
            [("100.3", entry)], {"slack-100.3": [page1, page2]}, self.kiosk_dir, 8, 30
        )
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["items"][0]["caption"], "Flyer for the summer party")
        self.assertEqual(manifest["items"][1]["caption"], "Flyer for the summer party")

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

    def test_video_becomes_a_video_manifest_item(self):
        video_path = self.kiosk_dir / "source" / "slack-100.8.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(video_path)], ts="100.8")
        manifest = refresh.build_manifest([("100.8", entry)], {}, self.kiosk_dir, 8, 30)
        self.assertEqual(manifest["items"], [
            {"kind": "video", "name": "slack-100.8.mp4", "src": "source/slack-100.8.mp4"},
        ])

    def test_video_with_caption_includes_caption_field(self):
        video_path = self.kiosk_dir / "source" / "slack-100.9.mov"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"x")
        entry = _attachment_entry(text="Team outing clip!", local_files=[str(video_path)], ts="100.9")
        manifest = refresh.build_manifest([("100.9", entry)], {}, self.kiosk_dir, 8, 30)
        self.assertEqual(manifest["items"][0]["caption"], "Team outing clip!")

    def test_single_heic_image_uses_the_converted_jpg(self):
        heic_path = self._make_image("slack-100.10.heic")
        converted = self.kiosk_dir / "rendered" / "heic" / "slack-100.10.jpg"
        converted.parent.mkdir(parents=True)
        converted.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(heic_path)], ts="100.10")
        manifest = refresh.build_manifest(
            [("100.10", entry)], {}, self.kiosk_dir, 8, 30,
            heic_rendered={str(heic_path): converted},
        )
        item = manifest["items"][0]
        self.assertEqual(item["kind"], "image")
        self.assertEqual(item["src"], "rendered/heic/slack-100.10.jpg")
        self.assertEqual(item["name"], "slack-100.10.heic")

    def test_heic_image_in_a_grid_uses_the_converted_jpg(self):
        heic_path = self._make_image("slack-100.11-0.heic")
        png_path = self._make_image("slack-100.11-1.png")
        converted = self.kiosk_dir / "rendered" / "heic" / "slack-100.11-0.jpg"
        converted.parent.mkdir(parents=True)
        converted.write_bytes(b"x")
        entry = _attachment_entry(text="", local_files=[str(heic_path), str(png_path)], ts="100.11")
        manifest = refresh.build_manifest(
            [("100.11", entry)], {}, self.kiosk_dir, 8, 30,
            heic_rendered={str(heic_path): converted},
        )
        regions = manifest["items"][0]["regions"]
        self.assertEqual(regions[0]["src"], "rendered/heic/slack-100.11-0.jpg")
        self.assertEqual(regions[1]["src"], "source/slack-100.11-1.png")


class CleanupStaleRendersTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.rendered_dir = self.tmp_dir / "rendered"
        self.rendered_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_removes_a_pdf_render_dir_no_longer_current(self):
        stale = self.rendered_dir / "slack-old.pdf"
        stale.mkdir()
        (stale / "page-1.png").write_bytes(b"x")
        refresh.cleanup_stale_renders(set(), self.rendered_dir)
        self.assertFalse(stale.exists())

    def test_keeps_a_pdf_render_dir_still_current(self):
        current = self.rendered_dir / "slack-current.pdf"
        current.mkdir()
        refresh.cleanup_stale_renders({"slack-current.pdf"}, self.rendered_dir)
        self.assertTrue(current.exists())

    def test_never_removes_the_reserved_heic_directory(self):
        # Regression: this directory isn't a PDF render -- it's where
        # render_heic_images() caches converted JPEGs. It used to get
        # treated as a stale PDF stem and wiped on every single tick,
        # forcing every HEIC image to be fully reconverted every time.
        heic_dir = self.rendered_dir / "heic"
        heic_dir.mkdir()
        (heic_dir / "slack-1.jpg").write_bytes(b"x")
        refresh.cleanup_stale_renders(set(), self.rendered_dir)
        self.assertTrue(heic_dir.exists())
        self.assertTrue((heic_dir / "slack-1.jpg").exists())


class RenderHeicImagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.tmp_dir / "source"
        self.source_dir.mkdir()
        self.rendered_dir = self.tmp_dir / "rendered"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_heic(self, name):
        import pillow_heif
        from PIL import Image
        path = self.source_dir / name
        img = Image.new("RGB", (40, 30), color=(200, 100, 50))
        heif_file = pillow_heif.from_pillow(img)
        heif_file.save(path, quality=80)
        return path

    def test_converts_heic_to_jpg(self):
        heic_path = self._write_heic("slack-1.heic")
        result = refresh.render_heic_images([heic_path], self.rendered_dir)
        self.assertEqual(set(result.keys()), {str(heic_path)})
        jpg_path = result[str(heic_path)]
        self.assertTrue(jpg_path.exists())
        self.assertEqual(jpg_path.suffix, ".jpg")

    def test_unchanged_heic_is_not_reconverted(self):
        heic_path = self._write_heic("slack-2.heic")
        refresh.render_heic_images([heic_path], self.rendered_dir)
        jpg_path = self.rendered_dir / "heic" / "slack-2.jpg"
        first_mtime = jpg_path.stat().st_mtime_ns

        refresh.render_heic_images([heic_path], self.rendered_dir)
        self.assertEqual(jpg_path.stat().st_mtime_ns, first_mtime)

    def test_corrupt_heic_is_skipped_without_raising(self):
        bad_path = self.source_dir / "bad.heic"
        bad_path.write_bytes(b"not a real heic file")
        result = refresh.render_heic_images([bad_path], self.rendered_dir)
        self.assertEqual(result, {})


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
