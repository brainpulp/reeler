"""Background jobs with live progress and a stop switch.

A generic Job runs a worker function in a daemon thread so the API stays
responsive, the UI can poll progress, and the user can stop it instantly.

Two workers:
- sniff: crawl the saved collection and download new reels (paced, network).
- scan: register reels already on disk into the library (local, no network).
"""
from __future__ import annotations

import threading
import time

from . import config, db, instagram, repo


class Job:
    """Runs one worker at a time, exposing a pollable progress dict."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._reset()

    def _reset(self) -> None:
        self.state: dict = {
            "running": False, "added": 0, "skipped": 0, "seen": 0,
            "done": False, "stopped": False, "error": None, "username": None,
        }

    def status(self) -> dict:
        return dict(self.state)

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def start(self, worker, *args) -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self._cancel.clear()
            self._reset()
            self.state["running"] = True
            self._thread = threading.Thread(
                target=self._run, args=(worker, args), daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._cancel.set()

    def _run(self, worker, args) -> None:
        try:
            worker(self, *args)
        except Exception as exc:
            self.state["error"] = str(exc)
        finally:
            self.state["running"] = False
            self.state["done"] = True


def _register(conn, post_or_code, owner=None, caption=None, path=None) -> None:
    repo.register_clip(
        conn, path=path, source="instagram",
        ig_shortcode=post_or_code, ig_owner=owner, caption=caption,
    )
    conn.commit()


def sniff_worker(job: Job, cookie_file, username, pause: float = 1.0) -> None:
    """Crawl saved reels and download new ones, paced and resumable."""
    loader, uname = instagram.build_session(cookie_file, username)
    job.state["username"] = uname
    with db.get_conn() as conn:
        for post in instagram.iter_saved(loader, uname, limit=None):
            if job.cancelled():
                job.state["stopped"] = True
                break
            job.state["seen"] += 1
            if repo.shortcode_exists(conn, post.shortcode):
                job.state["skipped"] += 1
                continue
            dest = config.LIBRARY_DIR / f"{post.shortcode}.mp4"
            if dest.exists():  # downloaded before; register without a network hit
                _register(conn, post.shortcode, post.owner, post.caption, dest)
                job.state["added"] += 1
                continue
            try:
                path = instagram.download_video(loader, post, config.LIBRARY_DIR)
            except Exception:
                continue
            _register(conn, post.shortcode, post.owner, post.caption, path)
            job.state["added"] += 1
            time.sleep(pause)  # pace only real downloads


def scan_worker(job: Job) -> None:
    """Register any .mp4 in the library that isn't catalogued yet — no network.

    Filenames are the Instagram shortcode (how the downloader names them), so we
    can surface reels downloaded on a previous run without touching Instagram.
    """
    files = sorted(config.LIBRARY_DIR.glob("*.mp4"))
    with db.get_conn() as conn:
        for f in files:
            if job.cancelled():
                job.state["stopped"] = True
                break
            job.state["seen"] += 1
            shortcode = f.stem
            if repo.shortcode_exists(conn, shortcode):
                job.state["skipped"] += 1
                continue
            try:
                _register(conn, shortcode, None, None, f)
                job.state["added"] += 1
            except Exception:
                continue


# One job for downloading, one for the local scan.
sniff_job = Job()
scan_job = Job()
