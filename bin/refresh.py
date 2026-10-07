#!/usr/bin/env python3
"""
refresh.py

One "tick" of Mess TV Bot's content pipeline:

  1. Poll a Slack channel for new/edited/deleted messages, downloading any
     attachments into a local "source" directory (see slack_source.py).
  2. Render any PDFs in that folder to PNG pages (poppler's pdftoppm),
     caching renders so unchanged PDFs aren't re-rendered every run.
  3. Write a manifest.json listing every slide (text posts, plain images,
     and PDF pages) in display order, for the kiosk webpage to poll.

Designed to be invoked repeatedly (systemd timer on the Pi, launchd or
cron on macOS, or just by hand). It never raises on a bad poll or a
missing tool -- it logs and leaves the previous manifest in place, so a
flaky network never blanks the display.

Config comes from environment variables (see config/kiosk.env.example).
If a path is given as argv[1], it's loaded as a simple KEY=VALUE file
first (handy for manual runs; systemd/launchd normally inject the env
directly).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pillow_heif
from PIL import Image

import slack_source

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
HEIC_EXTS = {".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
PDF_EXT = ".pdf"

pillow_heif.register_heif_opener()

log = logging.getLogger("kiosk")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class Config:
    slack_token: str
    slack_channel: str
    slack_ttl_days: int
    kiosk_dir: Path
    repo_dir: Path
    render_width: int
    slide_seconds: int
    poll_seconds: int
    skip_slack_poll: bool
    server_url: str
    admin_contact: str
    max_images: int
    max_pdf_pages: int
    max_attachment_mb: int

    @property
    def source_dir(self) -> Path:
        return self.kiosk_dir / "source"

    @property
    def rendered_dir(self) -> Path:
        return self.kiosk_dir / "rendered"

    @property
    def data_dir(self) -> Path:
        return self.kiosk_dir / "data"


def load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE loader so this script is testable without systemd."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(argv: list[str]) -> Config:
    if len(argv) > 1 and not argv[1].startswith("--"):
        load_env_file(Path(argv[1]).expanduser())

    slack_token = os.environ.get("KIOSK_SLACK_TOKEN", "").strip()
    slack_channel = os.environ.get("KIOSK_SLACK_CHANNEL", "").strip()
    if not slack_token or not slack_channel:
        log.error(
            "KIOSK_SLACK_TOKEN and KIOSK_SLACK_CHANNEL must both be set. "
            "Set them in config/kiosk.env."
        )
        sys.exit(2)

    kiosk_dir = Path(os.path.expandvars(os.environ.get("KIOSK_DIR", "~/kiosk-data"))).expanduser()
    # This file lives at <repo>/bin/refresh.py
    repo_dir = Path(os.environ.get("KIOSK_REPO", str(Path(__file__).resolve().parent.parent)))

    port = os.environ.get("KIOSK_PORT", "8420")
    default_server_url = f"http://{socket.gethostname()}:{port}"
    server_url = os.environ.get("KIOSK_SERVER_URL", "").strip() or default_server_url

    return Config(
        slack_token=slack_token,
        slack_channel=slack_channel,
        slack_ttl_days=int(os.environ.get("KIOSK_SLACK_TTL_DAYS", "30")),
        kiosk_dir=kiosk_dir,
        repo_dir=repo_dir,
        render_width=int(os.environ.get("KIOSK_RENDER_WIDTH", "1920")),
        slide_seconds=int(os.environ.get("KIOSK_SLIDE_SECONDS", "8")),
        poll_seconds=int(os.environ.get("KIOSK_POLL_SECONDS", "30")),
        skip_slack_poll=("--skip-slack-poll" in argv) or os.environ.get("KIOSK_SKIP_SLACK_POLL") == "1",
        server_url=server_url,
        admin_contact=os.environ.get("KIOSK_ADMIN_CONTACT", "@richard").strip(),
        max_images=int(os.environ.get("KIOSK_MAX_IMAGES", "6")),
        max_pdf_pages=int(os.environ.get("KIOSK_MAX_PDF_PAGES", "15")),
        max_attachment_mb=int(os.environ.get("KIOSK_MAX_ATTACHMENT_MB", "25")),
    )


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------

def ensure_dirs(cfg: Config) -> None:
    for d in (cfg.source_dir, cfg.rendered_dir, cfg.data_dir):
        d.mkdir(parents=True, exist_ok=True)


_PAGE_NUM_RE = re.compile(r"-(\d+)\.png$")


def _page_number(path: Path) -> int:
    m = _PAGE_NUM_RE.search(path.name)
    return int(m.group(1)) if m else 0


def _pdf_page_count(pdf: Path) -> int | None:
    """Total page count via pdfinfo, or None if it's unavailable/fails.
    Only used for the truncation log message -- rendering itself is
    bounded by pdftoppm's own -l flag regardless of whether this works."""
    try:
        result = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def render_pdfs(pdf_files: list[Path], rendered_dir: Path, width: int, max_pages: int) -> dict[str, list[Path]]:
    """Render each PDF to PNG pages, skipping ones already up to date.
    Rendering stops at max_pages (pdftoppm's -l flag) -- a PDF with far
    more pages than that was previously timing out the whole subprocess
    (120s) on a Pi 3B+, which also meant it retried that same expensive
    failure every single tick forever (no marker gets written on failure).
    Returns {pdf_stem: [sorted page image paths]}.
    """
    pages_by_stem: dict[str, list[Path]] = {}

    have_pdftoppm = shutil.which("pdftoppm") is not None
    if not have_pdftoppm and pdf_files:
        log.warning("pdftoppm not found; PDFs will be skipped (see docs/SETUP.md)")

    for pdf in pdf_files:
        stem = pdf.stem
        out_dir = rendered_dir / stem
        marker = out_dir / ".source_mtime"
        src_mtime = str(int(pdf.stat().st_mtime))

        needs_render = True
        if marker.exists() and marker.read_text().strip() == src_mtime:
            needs_render = False

        if needs_render and have_pdftoppm:
            total_pages = _pdf_page_count(pdf)
            if total_pages is not None and total_pages > max_pages:
                log.info("Rendering %s (%d pages, only keeping the first %d)",
                          pdf.name, total_pages, max_pages)
            else:
                log.info("Rendering %s", pdf.name)
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True)
            cmd = [
                "pdftoppm", "-png",
                "-scale-to-x", str(width),
                "-scale-to-y", "-1",
                "-l", str(max_pages),
                str(pdf), str(out_dir / "page"),
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    log.error("pdftoppm failed for %s: %s", pdf.name, result.stderr.strip())
                else:
                    marker.write_text(src_mtime)
            except (subprocess.TimeoutExpired, OSError) as exc:
                log.error("pdftoppm error for %s: %s", pdf.name, exc)

        if out_dir.exists():
            pages = sorted(out_dir.glob("page-*.png"), key=_page_number)
            if pages:
                pages_by_stem[stem] = pages

    return pages_by_stem


def render_heic_images(heic_files: list[Path], rendered_dir: Path) -> dict[str, Path]:
    """Convert each HEIC/HEIF image to a browser-displayable JPEG, skipping
    ones already up to date. Chromium has no built-in HEIC decoder, so these
    can't be referenced directly in the manifest the way other images are.
    Returns {str(original_path): converted_jpg_path}.
    """
    converted: dict[str, Path] = {}
    out_dir = rendered_dir / "heic"

    for heic_path in heic_files:
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{heic_path.stem}.jpg"
        marker = out_dir / f"{heic_path.stem}.source_mtime"
        src_mtime = str(int(heic_path.stat().st_mtime))

        needs_render = True
        if marker.exists() and marker.read_text().strip() == src_mtime and dest.exists():
            needs_render = False

        if needs_render:
            log.info("Converting HEIC image %s", heic_path.name)
            try:
                with Image.open(heic_path) as img:
                    img.convert("RGB").save(dest, "JPEG", quality=90)
                marker.write_text(src_mtime)
            except Exception as exc:  # noqa: BLE001 -- any decode/write failure, never fatal
                log.error("HEIC conversion failed for %s: %s", heic_path.name, exc)
                continue

        if dest.exists():
            converted[str(heic_path)] = dest

    return converted


# Subdirectories of rendered_dir that aren't a PDF-stem render and must
# never be swept by cleanup_stale_renders -- currently just render_heic_
# images()'s conversion cache.
RESERVED_RENDER_DIRS = {"heic"}


def cleanup_stale_renders(current_pdf_stems: set[str], rendered_dir: Path) -> None:
    if not rendered_dir.exists():
        return
    for entry in rendered_dir.iterdir():
        if not entry.is_dir() or entry.name in RESERVED_RENDER_DIRS:
            continue
        if entry.name not in current_pdf_stems:
            log.info("Removing stale render for deleted PDF: %s", entry.name)
            shutil.rmtree(entry, ignore_errors=True)


def cleanup_stale_heic_renders(current_heic_stems: set[str], rendered_dir: Path) -> None:
    heic_dir = rendered_dir / "heic"
    if not heic_dir.exists():
        return
    for jpg in heic_dir.glob("*.jpg"):
        if jpg.stem not in current_heic_stems:
            log.info("Removing stale HEIC conversion for deleted image: %s", jpg.stem)
            jpg.unlink(missing_ok=True)
            (heic_dir / f"{jpg.stem}.source_mtime").unlink(missing_ok=True)


def copy_site_assets(repo_dir: Path, kiosk_dir: Path) -> None:
    web_src = repo_dir / "web"
    if not web_src.exists():
        log.warning("No web/ assets found at %s", web_src)
        return
    for name in ("index.html", "style.css", "app.js"):
        src = web_src / name
        if src.exists():
            shutil.copyfile(src, kiosk_dir / name)

    admin_src = web_src / "admin"
    if admin_src.exists():
        admin_dest = kiosk_dir / "admin"
        admin_dest.mkdir(parents=True, exist_ok=True)
        for item in admin_src.iterdir():
            if item.is_file():
                shutil.copyfile(item, admin_dest / item.name)


def _relative_or_none(path: Path, kiosk_dir: Path, ts: object, label: str) -> str | None:
    try:
        return path.relative_to(kiosk_dir).as_posix()
    except ValueError:
        log.warning(
            "Skipping %s for ts=%s: file %s is not under kiosk_dir %s",
            label, ts, path, kiosk_dir,
        )
        return None


def build_manifest(active_entries: list[tuple[str, dict]], rendered_pages: dict[str, list[Path]],
                    kiosk_dir: Path, slide_seconds: int, poll_seconds: int,
                    heic_rendered: dict[str, Path] | None = None) -> dict:
    heic_rendered = heic_rendered or {}
    items = []
    for _ts, entry in active_entries:
        if entry["kind"] == "text":
            items.append({
                "kind": "text",
                "text": entry["text"],
                "author": entry["author"],
                "posted_at": entry["posted_at"],
            })
        elif entry["kind"] == "attachment" and entry.get("local_files"):
            local_files = [Path(f) for f in entry["local_files"]]
            file_path = local_files[0]
            if file_path.suffix.lower() == PDF_EXT:
                pages = rendered_pages.get(file_path.stem, [])
                total = len(pages)
                for i, page_path in enumerate(pages, start=1):
                    rel = _relative_or_none(page_path, kiosk_dir, entry.get("ts"), "manifest item")
                    if rel is None:
                        continue
                    item = {
                        "kind": "pdf-page", "name": file_path.name, "src": rel,
                        "page": i, "pages": total,
                    }
                    # Repeats on every page -- each page is its own slide
                    # shown at a different point in the rotation, not all
                    # at once, so repeating the caption keeps it in context
                    # regardless of which page a viewer happens to catch.
                    if entry.get("text"):
                        item["caption"] = entry["text"]
                    items.append(item)
            elif file_path.suffix.lower() in VIDEO_EXTS:
                rel = _relative_or_none(file_path, kiosk_dir, entry.get("ts"), "manifest item")
                if rel is not None:
                    item = {"kind": "video", "name": file_path.name, "src": rel}
                    if entry.get("text"):
                        item["caption"] = entry["text"]
                    items.append(item)
            elif len(local_files) > 1:
                regions = []
                if entry.get("text"):
                    regions.append({"kind": "text", "text": entry["text"]})
                for img_path in local_files:
                    display_path = heic_rendered.get(str(img_path), img_path)
                    rel = _relative_or_none(display_path, kiosk_dir, entry.get("ts"), "grid region")
                    if rel is None:
                        continue
                    regions.append({"kind": "image", "src": rel, "name": img_path.name})
                if regions:
                    items.append({"kind": "grid", "regions": regions})
            else:
                display_path = heic_rendered.get(str(file_path), file_path)
                rel = _relative_or_none(display_path, kiosk_dir, entry.get("ts"), "manifest item")
                if rel is None:
                    continue
                item = {"kind": "image", "name": file_path.name, "src": rel}
                if entry.get("text"):
                    item["caption"] = entry["text"]
                items.append(item)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "slide_seconds": slide_seconds,
        "poll_seconds": poll_seconds,
        "items": items,
    }


def write_manifest(manifest: dict, data_dir: Path) -> None:
    final_path = data_dir / "manifest.json"
    fd, tmp_name = tempfile.mkstemp(dir=data_dir, prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(manifest, fh, indent=2)
        os.replace(tmp_name, final_path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("KIOSK_LOG_LEVEL", "INFO"),
        format="%(asctime)s kiosk %(levelname)s: %(message)s",
    )
    cfg = load_config(argv)
    ensure_dirs(cfg)
    copy_site_assets(cfg.repo_dir, cfg.kiosk_dir)

    state_path = cfg.data_dir / "slack-state.json"

    if cfg.skip_slack_poll:
        log.info("Skipping Slack poll (--skip-slack-poll / KIOSK_SKIP_SLACK_POLL=1)")
        state = slack_source.load_state(state_path)
    else:
        api = slack_source.SlackWebAPI(cfg.slack_token)
        try:
            bot_user_id = api.auth_test()
        except slack_source.SlackAPIError as exc:
            log.error("Failed to resolve bot's own user ID (auth.test): %s -- "
                       "bot messages won't be excluded from ingestion this tick", exc)
            bot_user_id = ""
        slack_cfg = slack_source.SlackConfig(
            cfg.slack_token, cfg.slack_channel, cfg.slack_ttl_days, bot_user_id,
            server_url=cfg.server_url, admin_contact=cfg.admin_contact, max_images=cfg.max_images,
            max_attachment_bytes=cfg.max_attachment_mb * 1024 * 1024,
        )
        with slack_source.state_lock(state_path):
            state = slack_source.load_state(state_path)
            state = slack_source.poll_slack(
                slack_cfg, state, cfg.source_dir, datetime.now(timezone.utc), api,
                audit_path=cfg.data_dir / "audit.jsonl",
            )
            slack_source.save_state(state, state_path)

    active_entries = slack_source.sorted_active_entries(state)
    pdf_files = [
        Path(entry["local_files"][0])
        for _ts, entry in active_entries
        if entry["kind"] == "attachment" and entry.get("local_files")
        and Path(entry["local_files"][0]).suffix.lower() == PDF_EXT
    ]
    # HEIC images can appear anywhere in local_files (single image or one of
    # several in a grid post), not just local_files[0] like PDF/video.
    heic_files = [
        Path(f)
        for _ts, entry in active_entries
        if entry["kind"] == "attachment"
        for f in entry.get("local_files", [])
        if Path(f).suffix.lower() in HEIC_EXTS
    ]

    rendered_pages = render_pdfs(pdf_files, cfg.rendered_dir, cfg.render_width, cfg.max_pdf_pages)
    cleanup_stale_renders({f.stem for f in pdf_files}, cfg.rendered_dir)
    heic_rendered = render_heic_images(heic_files, cfg.rendered_dir)
    cleanup_stale_heic_renders({f.stem for f in heic_files}, cfg.rendered_dir)

    manifest = build_manifest(active_entries, rendered_pages, cfg.kiosk_dir, cfg.slide_seconds, cfg.poll_seconds,
                               heic_rendered=heic_rendered)
    write_manifest(manifest, cfg.data_dir)

    log.info("Refresh complete: %d slide(s) from %d active Slack message(s)",
              len(manifest["items"]), len(active_entries))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
