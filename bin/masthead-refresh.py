#!/usr/bin/env python3
"""
masthead-refresh.py

One "tick" of Masthead's content pipeline:

  1. Poll a Slack channel for new/edited/deleted messages, downloading any
     attachments into a local "source" directory (see masthead_slack.py).
  2. Render any PDFs in that folder to PNG pages (poppler's pdftoppm),
     caching renders so unchanged PDFs aren't re-rendered every run.
  3. Write a manifest.json listing every slide (text posts, plain images,
     and PDF pages) in display order, for the kiosk webpage to poll.

Designed to be invoked repeatedly (systemd timer on the Pi, launchd or
cron on macOS, or just by hand). It never raises on a bad poll or a
missing tool -- it logs and leaves the previous manifest in place, so a
flaky network never blanks the display.

Config comes from environment variables (see config/masthead.env.example).
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
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import masthead_slack

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
PDF_EXT = ".pdf"

log = logging.getLogger("masthead")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class Config:
    slack_token: str
    slack_channel: str
    slack_ttl_days: int
    masthead_dir: Path
    repo_dir: Path
    render_width: int
    slide_seconds: int
    poll_seconds: int
    skip_slack_poll: bool

    @property
    def source_dir(self) -> Path:
        return self.masthead_dir / "source"

    @property
    def rendered_dir(self) -> Path:
        return self.masthead_dir / "rendered"

    @property
    def data_dir(self) -> Path:
        return self.masthead_dir / "data"


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

    slack_token = os.environ.get("MASTHEAD_SLACK_TOKEN", "").strip()
    slack_channel = os.environ.get("MASTHEAD_SLACK_CHANNEL", "").strip()
    if not slack_token or not slack_channel:
        log.error(
            "MASTHEAD_SLACK_TOKEN and MASTHEAD_SLACK_CHANNEL must both be set. "
            "Set them in config/masthead.env."
        )
        sys.exit(2)

    masthead_dir = Path(os.path.expandvars(os.environ.get("MASTHEAD_DIR", "~/masthead-data"))).expanduser()
    # This file lives at <repo>/bin/masthead-refresh.py
    repo_dir = Path(os.environ.get("MASTHEAD_REPO", str(Path(__file__).resolve().parent.parent)))

    return Config(
        slack_token=slack_token,
        slack_channel=slack_channel,
        slack_ttl_days=int(os.environ.get("MASTHEAD_SLACK_TTL_DAYS", "30")),
        masthead_dir=masthead_dir,
        repo_dir=repo_dir,
        render_width=int(os.environ.get("MASTHEAD_RENDER_WIDTH", "1920")),
        slide_seconds=int(os.environ.get("MASTHEAD_SLIDE_SECONDS", "8")),
        poll_seconds=int(os.environ.get("MASTHEAD_POLL_SECONDS", "30")),
        skip_slack_poll=("--skip-slack-poll" in argv) or os.environ.get("MASTHEAD_SKIP_SLACK_POLL") == "1",
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


def render_pdfs(pdf_files: list[Path], rendered_dir: Path, width: int) -> dict[str, list[Path]]:
    """Render each PDF to PNG pages, skipping ones already up to date.
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
            log.info("Rendering %s", pdf.name)
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True)
            cmd = [
                "pdftoppm", "-png",
                "-scale-to-x", str(width),
                "-scale-to-y", "-1",
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


def cleanup_stale_renders(current_pdf_stems: set[str], rendered_dir: Path) -> None:
    if not rendered_dir.exists():
        return
    for entry in rendered_dir.iterdir():
        if entry.is_dir() and entry.name not in current_pdf_stems:
            log.info("Removing stale render for deleted PDF: %s", entry.name)
            shutil.rmtree(entry, ignore_errors=True)


def copy_site_assets(repo_dir: Path, masthead_dir: Path) -> None:
    web_src = repo_dir / "web"
    if not web_src.exists():
        log.warning("No web/ assets found at %s", web_src)
        return
    for name in ("index.html", "style.css", "app.js"):
        src = web_src / name
        if src.exists():
            shutil.copyfile(src, masthead_dir / name)


def build_manifest(active_entries: list[tuple[str, dict]], rendered_pages: dict[str, list[Path]],
                    masthead_dir: Path, slide_seconds: int, poll_seconds: int) -> dict:
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
            file_path = Path(entry["local_files"][0])
            if file_path.suffix.lower() == PDF_EXT:
                pages = rendered_pages.get(file_path.stem, [])
                total = len(pages)
                for i, page_path in enumerate(pages, start=1):
                    try:
                        rel = page_path.relative_to(masthead_dir).as_posix()
                    except ValueError:
                        log.warning(
                            "Skipping manifest item for %s (ts=%s): rendered page %s is not "
                            "under masthead_dir %s", file_path.name, entry.get("ts"), page_path, masthead_dir,
                        )
                        continue
                    items.append({
                        "kind": "pdf-page", "name": file_path.name, "src": rel,
                        "page": i, "pages": total,
                    })
            else:
                try:
                    rel = file_path.relative_to(masthead_dir).as_posix()
                except ValueError:
                    log.warning(
                        "Skipping manifest item for %s (ts=%s): file %s is not under masthead_dir %s",
                        file_path.name, entry.get("ts"), file_path, masthead_dir,
                    )
                    continue
                items.append({"kind": "image", "name": file_path.name, "src": rel})

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
        level=os.environ.get("MASTHEAD_LOG_LEVEL", "INFO"),
        format="%(asctime)s masthead %(levelname)s: %(message)s",
    )
    cfg = load_config(argv)
    ensure_dirs(cfg)
    copy_site_assets(cfg.repo_dir, cfg.masthead_dir)

    state_path = cfg.data_dir / "slack-state.json"
    state = masthead_slack.load_state(state_path)

    if cfg.skip_slack_poll:
        log.info("Skipping Slack poll (--skip-slack-poll / MASTHEAD_SKIP_SLACK_POLL=1)")
    else:
        api = masthead_slack.SlackWebAPI(cfg.slack_token)
        try:
            bot_user_id = api.auth_test()
        except masthead_slack.SlackAPIError as exc:
            log.error("Failed to resolve bot's own user ID (auth.test): %s -- "
                       "bot messages won't be excluded from ingestion this tick", exc)
            bot_user_id = ""
        slack_cfg = masthead_slack.SlackConfig(cfg.slack_token, cfg.slack_channel, cfg.slack_ttl_days, bot_user_id)
        state = masthead_slack.poll_slack(slack_cfg, state, cfg.source_dir, datetime.now(timezone.utc), api)
        masthead_slack.save_state(state, state_path)

    active_entries = masthead_slack.sorted_active_entries(state)
    pdf_files = [
        Path(entry["local_files"][0])
        for _ts, entry in active_entries
        if entry["kind"] == "attachment" and entry.get("local_files")
        and Path(entry["local_files"][0]).suffix.lower() == PDF_EXT
    ]

    rendered_pages = render_pdfs(pdf_files, cfg.rendered_dir, cfg.render_width)
    cleanup_stale_renders({f.stem for f in pdf_files}, cfg.rendered_dir)

    manifest = build_manifest(active_entries, rendered_pages, cfg.masthead_dir, cfg.slide_seconds, cfg.poll_seconds)
    write_manifest(manifest, cfg.data_dir)

    log.info("Refresh complete: %d slide(s) from %d active Slack message(s)",
              len(manifest["items"]), len(active_entries))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
