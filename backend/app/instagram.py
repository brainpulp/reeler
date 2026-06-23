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

import time
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
        max_connection_attempts=1,  # fail fast on bad/expired auth
        request_timeout=20.0,       # default is 300s — don't hang the request
        quiet=True,
    )
    jar = MozillaCookieJar(cookie_file)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:  # malformed / wrong-format file
        raise RuntimeError(f"Could not read cookie file: {exc}")

    # Inspect the user's exported cookies specifically — instaloader's own
    # anonymous session already carries a csrftoken, so checking the merged
    # session would mask a cookie file that's missing the logged-in token.
    jar_cookies = {c.name: c.value for c in jar}
    if "csrftoken" not in jar_cookies or "sessionid" not in jar_cookies:
        raise RuntimeError(
            "Cookie file is missing 'csrftoken'/'sessionid' for instagram.com — "
            "export cookies for the instagram.com domain while logged in."
        )

    session = loader.context._session
    session.cookies.update(jar)
    # instaloader's own load_session sets this header; authenticated GraphQL
    # queries (e.g. saved posts) are rejected without it.
    session.headers.update({"X-CSRFToken": jar_cookies["csrftoken"]})

    test_login = loader.test_login()
    if not test_login:
        raise RuntimeError(
            "Instagram cookies did not authenticate. Re-export them while "
            "logged in (they may have expired)."
        )
    loader.context.username = test_login
    if username and username != test_login:
        # The saved-posts query requires the logged-in account; honor it.
        pass
    return loader, test_login


# Instagram's public web client app id; required header for the private web API.
_IG_APP_ID = "936619743392459"
_SAVED_URL = "https://www.instagram.com/api/v1/feed/saved/posts/"


def _videos_in_media(media: dict) -> list[FetchedPost]:
    """Extract downloadable video posts from one saved media item.

    Handles single videos and carousels (albums with multiple slides).
    media_type 2 == video.
    """
    owner = (media.get("user") or {}).get("username", "")
    caption_obj = media.get("caption") or {}
    caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""
    base_code = media.get("code") or ""

    slides = media.get("carousel_media") or [media]
    out: list[FetchedPost] = []
    for i, slide in enumerate(slides):
        if slide.get("media_type") != 2:
            continue
        versions = slide.get("video_versions") or []
        if not versions:
            continue
        code = slide.get("code") or base_code
        # Disambiguate multiple video slides under one post so DB rows don't collide.
        shortcode = code if len(slides) == 1 else f"{code}_{i}"
        out.append(FetchedPost(
            shortcode=shortcode,
            owner=owner,
            caption=caption,
            video_url=versions[0]["url"],
        ))
    return out


def iter_saved(loader, username: str, limit: int | None = None) -> Iterator[FetchedPost]:
    """Yield saved video posts via Instagram's current private web API.

    instaloader's Profile.get_saved_posts() still targets a GraphQL query hash
    that Instagram has retired, so we call the saved-feed endpoint the website
    itself uses, reusing the authenticated session.
    """
    session = loader.context._session
    headers = {"X-IG-App-ID": _IG_APP_ID, "Referer": "https://www.instagram.com/"}
    params: dict = {}
    count = 0
    while True:
        resp = session.get(_SAVED_URL, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Saved feed request failed (HTTP {resp.status_code}). "
                "Your session may have expired — re-export cookies."
            )
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(
                "Saved feed did not return JSON (Instagram may be rate-limiting "
                "or the session is invalid). Try again shortly."
            )
        for item in data.get("items", []):
            media = item.get("media") or item
            for post in _videos_in_media(media):
                yield post
                count += 1
                if limit and count >= limit:
                    return
        if not data.get("more_available") or not data.get("next_max_id"):
            break
        params["max_id"] = data["next_max_id"]
        time.sleep(1.0)  # pace pagination to stay under rate limits


_COLLECTIONS_URL = "https://www.instagram.com/api/v1/collections/list/"
_COLLECTION_FEED = "https://www.instagram.com/api/v1/feed/collection/{cid}/posts/"


def list_collections(loader) -> list[dict]:
    """Return the account's named saved-collections: [{id, name}, ...].

    Skips the auto 'All Posts' collection (everything is already in the flat
    saved feed); only user-named collections are useful for grouping.
    """
    session = loader.context._session
    headers = {"X-IG-App-ID": _IG_APP_ID, "Referer": "https://www.instagram.com/"}
    params = {"collection_types": '["MEDIA"]'}
    resp = session.get(_COLLECTIONS_URL, params=params, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"collections list failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("collections list did not return JSON (session/rate-limit)")
    out = []
    for item in data.get("items", []):
        if item.get("collection_type") == "ALL_MEDIA_AUTO_COLLECTION":
            continue
        cid = item.get("collection_id")
        name = item.get("collection_name")
        if cid and name:
            out.append({"id": str(cid), "name": name})
    return out


def iter_collection_posts(loader, collection_id: str) -> Iterator[FetchedPost]:
    """Yield video posts in one collection (paginated)."""
    session = loader.context._session
    headers = {"X-IG-App-ID": _IG_APP_ID, "Referer": "https://www.instagram.com/"}
    url = _COLLECTION_FEED.format(cid=collection_id)
    params: dict = {}
    while True:
        resp = session.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"collection feed failed (HTTP {resp.status_code})")
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("collection feed did not return JSON (session/rate-limit)")
        for item in data.get("items", []):
            media = item.get("media") or item
            for post in _videos_in_media(media):
                yield post
        if not data.get("more_available") or not data.get("next_max_id"):
            break
        params["max_id"] = data["next_max_id"]
        time.sleep(1.0)


def download_video(loader, post: FetchedPost, dest_dir: Path) -> Path:
    """Download a single post's video file to dest_dir, return the path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{post.shortcode}.mp4"
    # instaloader's context handles the authenticated GET + retries.
    loader.context.get_and_write_raw(post.video_url, str(out))
    return out
