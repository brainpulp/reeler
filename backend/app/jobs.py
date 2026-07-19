"""Background jobs with live progress and a stop switch.

A generic Job runs a worker function in a daemon thread so the API stays
responsive, the UI can poll progress, and the user can stop it instantly.

Two workers:
- sniff: crawl the saved collection and download new reels (paced, network).
- scan: register reels already on disk into the library (local, no network).
"""
from __future__ import annotations

import random
import threading
import time

from . import config, db, instagram, repo

# --- Instagram safety limits (see CLAUDE.md "Instagram safety & scheduling") ---
# A single sniff run never downloads more than this many *new* reels, so one
# click/run can't become a 1000-video burst that risks an action-block.
MAX_NEW_PER_RUN = 150
# Jittered delay between real network downloads (seconds). Randomized so the
# request cadence doesn't look robotic.
PACE_MIN, PACE_MAX = 1.5, 3.0


class Job:
    """Runs one worker at a time, exposing a pollable progress dict."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._reset()

    def _reset(self) -> None:
        self.state: dict = {
            "running": False, "added": 0, "downloaded": 0, "skipped": 0,
            "seen": 0, "done": False, "stopped": False, "capped": False,
            "error": None, "username": None,
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


def sniff_worker(job: Job, cookie_file, username,
                 max_new: int = MAX_NEW_PER_RUN) -> None:
    """Crawl saved reels and download new ones — paced, capped, and resumable.

    Stops after `max_new` *network downloads* (the safety cap), on cancel, or
    when the feed is exhausted. Reels already on disk are registered for free
    and don't count against the cap. Any Instagram error aborts the run (the
    feed iterator raises on non-200 / rate-limit responses).
    """
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
            # Safety cap: never let one run become a large burst.
            if max_new and job.state["downloaded"] >= max_new:
                job.state["capped"] = True
                break
            try:
                path = instagram.download_video(loader, post, config.LIBRARY_DIR)
            except Exception:
                continue
            _register(conn, post.shortcode, post.owner, post.caption, path)
            job.state["added"] += 1
            job.state["downloaded"] += 1
            time.sleep(random.uniform(PACE_MIN, PACE_MAX))  # jittered, real downloads only


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


def collections_worker(job: Job, cookie_file, username, max_pages=None) -> None:
    """Map each saved collection's reels onto local clips — metadata only.

    Fetches the account's named collections and their post lists, cataloging
    each reel as a link and setting its collection. Never downloads a video.
    Paced, cancellable, aborts on any Instagram error. max_pages caps depth per
    collection for light routine updates (new reels are at the top).
    """
    loader, uname = instagram.build_session(cookie_file, username)
    job.state["username"] = uname
    collections = instagram.list_collections(loader)
    with db.get_conn() as conn:
        for coll in collections:
            if job.cancelled():
                job.state["stopped"] = True
                break
            planned = lambda sc: str(
                (config.LIBRARY_DIR / f"{sc}.mp4").relative_to(config.DATA_DIR)
            )
            for post in instagram.iter_collection_posts(
                loader, coll["id"], max_pages=max_pages
            ):
                if job.cancelled():
                    job.state["stopped"] = True
                    break
                job.state["seen"] += 1
                # Catalog every reel in the collection as a link (metadata only,
                # no video download) so non-downloaded reels still show, grouped.
                if not repo.shortcode_exists(conn, post.shortcode):
                    repo.register_indexed(
                        conn, shortcode=post.shortcode, media_id=post.media_id,
                        owner=post.owner, caption=post.caption,
                        thumb_rel=None, planned_rel=planned(post.shortcode),
                    )
                repo.set_collection(
                    conn, post.shortcode, coll["name"], post.owner, post.caption
                )
                job.state["added"] += 1
                conn.commit()
            time.sleep(1.0)  # pace between collections


MAX_INDEX_PER_RUN = 300  # thumbnails are light, but still cap per run


def index_worker(job: Job, cookie_file, username,
                 max_new: int = MAX_INDEX_PER_RUN) -> None:
    """Metadata-first catalog: store metadata + a thumbnail per reel, NO video.

    This is the cheap 'organized access' pull — browse 1000+ reels having
    downloaded almost nothing. Videos are fetched lazily later, only when used.
    Same safety discipline as the sniff (paced, capped, cancellable, abort-on-error).
    """
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
            if max_new and job.state["downloaded"] >= max_new:
                job.state["capped"] = True
                break
            thumb_rel = None
            if post.thumb_url:
                try:
                    dest = config.THUMBS_DIR / f"{post.shortcode}.jpg"
                    instagram.download_thumbnail(loader, post.thumb_url, dest)
                    thumb_rel = str(dest.relative_to(config.DATA_DIR))
                except Exception:
                    thumb_rel = None
            planned_rel = str(
                (config.LIBRARY_DIR / f"{post.shortcode}.mp4").relative_to(config.DATA_DIR)
            )
            repo.register_indexed(
                conn, shortcode=post.shortcode, media_id=post.media_id,
                owner=post.owner, caption=post.caption,
                thumb_rel=thumb_rel, planned_rel=planned_rel,
            )
            conn.commit()
            job.state["added"] += 1
            job.state["downloaded"] += 1  # thumbnail fetch = the network action
            time.sleep(random.uniform(0.6, 1.4))


def feed_collections_worker(job: Job, cookie_file, username, max_reels=4000) -> None:
    """Assign collections from the SAVED FEED (which works), not the blocked
    collections endpoint. Each reel's `saved_collection_ids` rides along with
    the feed; we store them, then learn id->name from reels that already have a
    name and apply names to the rest. Metadata only, paced, cancellable.
    """
    loader, uname = instagram.build_session(cookie_file, username)
    job.state["username"] = uname
    with db.get_conn() as conn:
        for post in instagram.iter_saved(loader, uname, limit=None):
            if job.cancelled():
                job.state["stopped"] = True
                break
            job.state["seen"] += 1
            if not repo.shortcode_exists(conn, post.shortcode):
                planned = str(
                    (config.LIBRARY_DIR / f"{post.shortcode}.mp4").relative_to(config.DATA_DIR)
                )
                repo.register_indexed(
                    conn, shortcode=post.shortcode, media_id=post.media_id,
                    owner=post.owner, caption=post.caption,
                    thumb_rel=None, planned_rel=planned,
                )
                job.state["added"] += 1
            repo.set_collection_ids(conn, post.shortcode, post.collection_ids)
            # The feed already carries a cover URL — store it so indexed reels
            # show a thumbnail in the grid without downloading anything.
            repo.set_thumb_url(conn, post.shortcode, post.thumb_url)
            conn.commit()
            if job.state["seen"] >= max_reels:
                job.state["capped"] = True
                break
        # Marry collection ids to the names you already have, then label the rest.
        id_name = repo.collection_id_name_map(conn)
        job.state["named"] = repo.apply_collection_names(conn, id_name)
        job.state["collections_known"] = len(set(id_name.values()))
        conn.commit()


# Jobs: full download sniff, local scan, collection backfill, metadata index.
sniff_job = Job()
scan_job = Job()
collections_job = Job()
index_job = Job()
