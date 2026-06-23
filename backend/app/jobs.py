"""Background saved-reel sniffing with live progress and a stop switch.

Runs the long crawl in a daemon thread so the API stays responsive, the UI can
poll progress, and the user can stop it instantly. Safe to re-run: reels already
in the library (or already downloaded to disk) are skipped without hitting
Instagram, and only real network downloads are paced.
"""
from __future__ import annotations

import threading
import time

from . import config, db, instagram, repo


class SniffJob:
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

    def start(self, cookie_file: str | None, username: str | None,
              pause: float = 1.0) -> bool:
        """Begin a crawl. Returns False if one is already running."""
        with self._lock:
            if self.state["running"]:
                return False
            self._cancel.clear()
            self._reset()
            self.state["running"] = True
            self._thread = threading.Thread(
                target=self._run, args=(cookie_file, username, pause), daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._cancel.set()

    def _run(self, cookie_file, username, pause) -> None:
        try:
            loader, uname = instagram.build_session(cookie_file, username)
            self.state["username"] = uname
            with db.get_conn() as conn:
                for post in instagram.iter_saved(loader, uname, limit=None):
                    if self._cancel.is_set():
                        self.state["stopped"] = True
                        break
                    self.state["seen"] += 1

                    # Already catalogued — nothing to do, no network hit.
                    if repo.shortcode_exists(conn, post.shortcode):
                        self.state["skipped"] += 1
                        continue

                    dest = config.LIBRARY_DIR / f"{post.shortcode}.mp4"
                    if dest.exists():
                        # Downloaded on a prior run but not catalogued; register
                        # it locally without re-downloading from Instagram.
                        repo.register_clip(
                            conn, path=dest, source="instagram",
                            ig_shortcode=post.shortcode, ig_owner=post.owner,
                            caption=post.caption,
                        )
                        conn.commit()
                        self.state["added"] += 1
                        continue

                    try:
                        path = instagram.download_video(
                            loader, post, config.LIBRARY_DIR
                        )
                    except Exception:  # per-post network hiccup; skip it
                        continue
                    repo.register_clip(
                        conn, path=path, source="instagram",
                        ig_shortcode=post.shortcode, ig_owner=post.owner,
                        caption=post.caption,
                    )
                    conn.commit()
                    self.state["added"] += 1
                    time.sleep(pause)  # pace only real downloads
        except Exception as exc:
            self.state["error"] = str(exc)
        finally:
            self.state["running"] = False
            self.state["done"] = True


# Single shared job for this single-user local app.
job = SniffJob()
