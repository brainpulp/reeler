"""Instagram ingestion via a logged-in session (the 'sniff' stage).

We never handle the user's password. Instead the user logs into Instagram in
their browser and exports cookies; we load that session into instaloader and
iterate their *own* Saved collection. This is personal, local archival of
content the account already has access to.

Export a Netscape-format cookies.txt from your browser (e.g. the
"Get cookies.txt LOCALLY" extension) for instagram.com and point
REELER_IG_COOKIE_FILE at it.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Iterator

from . import config


@dataclass
class FetchedPost:
    shortcode: str
    owner: str
    caption: str
    video_url: str


def _load_instaloader():
    try:
        import instaloader  # noqa: WPS433 (lazy import; optional heavy dep)
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "instaloader is not installed; run pip install -r requirements.txt"
        ) from exc
    return instaloader


def build_session(cookie_file: str | None = None, username: str | None = None):
    """Return an authenticated instaloader.Instaloader using browser cookies."""
    instaloader = _load_instaloader()
    cookie_file = cookie_file or config.IG_COOKIE_FILE
    username = username or config.IG_USERNAME
    if not cookie_file or not Path(cookie_file).exists():
        raise RuntimeError(
            "No Instagram cookie file found. Set REELER_IG_COOKIE_FILE to an "
            "exported cookies.txt for instagram.com."
        )

    loader = instaloader.Instaloader(
        download_pictures=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )
    jar = MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    loader.context._session.cookies.update(jar)
    test_login = loader.test_login()
    if not test_login:
        raise RuntimeError(
            "Instagram cookies did not authenticate. Re-export them while "
            "logged in."
        )
    loader.context.username = test_login
    return loader, test_login


def iter_saved(loader, username: str, limit: int | None = None) -> Iterator[FetchedPost]:
    """Yield video posts from the account's Saved collection."""
    instaloader = _load_instaloader()
    profile = instaloader.Profile.from_username(loader.context, username)
    count = 0
    for post in profile.get_saved_posts():
        if not post.is_video:
            continue
        yield FetchedPost(
            shortcode=post.shortcode,
            owner=post.owner_username,
            caption=post.caption or "",
            video_url=post.video_url,
        )
        count += 1
        if limit and count >= limit:
            break


def download_video(loader, post: FetchedPost, dest_dir: Path) -> Path:
    """Download a single post's video file to dest_dir, return the path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{post.shortcode}.mp4"
    # instaloader's context handles the authenticated GET + retries.
    loader.context.get_and_write_raw(post.video_url, str(out))
    return out
