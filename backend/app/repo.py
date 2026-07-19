"""Persistence helpers that turn files on disk into clip rows and back.

This is the bridge between media.py (pure file ops) and the API: it probes a
file, generates a thumbnail, and records everything in SQLite.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, media


def _rel(path: Path) -> str:
    return str(path.relative_to(config.DATA_DIR))


def register_clip(
    conn: sqlite3.Connection,
    *,
    path: Path,
    source: str,
    ig_shortcode: str | None = None,
    ig_owner: str | None = None,
    caption: str | None = None,
    op: dict | None = None,
    kept: int = 0,
) -> int:
    """Probe + thumbnail a real file already on disk and insert a clip row."""
    info = media.probe(path)
    try:
        thumb = media.make_thumbnail(path)
        thumb_rel = _rel(thumb)
    except media.MediaError:
        thumb_rel = None

    values = (
        source, ig_shortcode, ig_owner, caption, path.name, _rel(path),
        1, kept, info.width, info.height, info.duration, info.fps, thumb_rel,
        json.dumps(op) if op else None,
    )
    cols = (
        "(source, ig_shortcode, ig_owner, caption, filename, rel_path, "
        "has_video, kept, width, height, duration, fps, thumb_rel, op)"
    )
    ph = "?,?,?,?,?,?,?,?,?,?,?,?,?,?"
    if ig_shortcode is None:
        cur = conn.execute(f"INSERT INTO clips {cols} VALUES ({ph})", values)
        return cur.lastrowid

    # Instagram clips: re-registering the same shortcode upgrades it to a real
    # file (e.g. an indexed reel that's now been downloaded).
    conn.execute(
        f"""
        INSERT INTO clips {cols} VALUES ({ph})
        ON CONFLICT(ig_shortcode) WHERE ig_shortcode IS NOT NULL
        DO UPDATE SET caption = COALESCE(NULLIF(excluded.caption,''), caption),
                      filename = excluded.filename, rel_path = excluded.rel_path,
                      has_video = 1, width = excluded.width, height = excluded.height,
                      duration = excluded.duration, fps = excluded.fps,
                      thumb_rel = COALESCE(excluded.thumb_rel, thumb_rel)
        """,
        values,
    )
    return conn.execute(
        "SELECT id FROM clips WHERE ig_shortcode = ?", (ig_shortcode,)
    ).fetchone()["id"]


def register_indexed(
    conn: sqlite3.Connection, *, shortcode: str, media_id: str,
    owner: str | None, caption: str | None, thumb_rel: str | None,
    planned_rel: str,
) -> int:
    """Insert/refresh a metadata-only catalog entry (no video downloaded)."""
    conn.execute(
        """
        INSERT INTO clips
            (source, ig_shortcode, ig_owner, caption, filename, rel_path,
             media_id, has_video, kept, thumb_rel)
        VALUES ('instagram', ?, ?, ?, ?, ?, ?, 0, 0, ?)
        ON CONFLICT(ig_shortcode) WHERE ig_shortcode IS NOT NULL
        DO UPDATE SET media_id = excluded.media_id,
                      ig_owner = COALESCE(NULLIF(excluded.ig_owner,''), ig_owner),
                      caption  = COALESCE(NULLIF(excluded.caption,''), caption),
                      thumb_rel = COALESCE(excluded.thumb_rel, thumb_rel)
        """,
        (shortcode, owner, caption, f"{shortcode}.mp4", planned_rel,
         media_id, thumb_rel),
    )
    return conn.execute(
        "SELECT id FROM clips WHERE ig_shortcode = ?", (shortcode,)
    ).fetchone()["id"]


def mark_video_downloaded(conn: sqlite3.Connection, clip_id: int, path: Path) -> None:
    """After a lazy download, probe the file and flip has_video on."""
    info = media.probe(path)
    try:
        thumb_rel = _rel(media.make_thumbnail(path))
    except media.MediaError:
        thumb_rel = None
    conn.execute(
        """
        UPDATE clips SET rel_path=?, filename=?, has_video=1,
               width=?, height=?, duration=?, fps=?,
               thumb_rel=COALESCE(?, thumb_rel)
         WHERE id=?
        """,
        (_rel(path), path.name, info.width, info.height, info.duration,
         info.fps, thumb_rel, clip_id),
    )


def set_kept(conn: sqlite3.Connection, clip_id: int, kept: int) -> None:
    conn.execute("UPDATE clips SET kept=? WHERE id=?", (kept, clip_id))


def clean_working_copies(conn: sqlite3.Connection) -> int:
    """Delete downloaded videos that aren't kept (temporary working copies)."""
    rows = conn.execute(
        "SELECT id, rel_path FROM clips "
        "WHERE has_video=1 AND kept=0 AND source='instagram'"
    ).fetchall()
    n = 0
    for r in rows:
        p = config.DATA_DIR / r["rel_path"]
        try:
            if p.exists():
                p.unlink()
            conn.execute("UPDATE clips SET has_video=0 WHERE id=?", (r["id"],))
            n += 1
        except OSError:
            continue
    return n


def get_clip(conn: sqlite3.Connection, clip_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()


def shortcode_exists(conn: sqlite3.Connection, shortcode: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM clips WHERE ig_shortcode = ? LIMIT 1", (shortcode,)
    ).fetchone() is not None


def clip_path(row: sqlite3.Row) -> Path:
    return config.DATA_DIR / row["rel_path"]


def list_clips(
    conn: sqlite3.Connection,
    tag: str | None = None,
    collection: str | None = None,
) -> list[dict]:
    where, params = [], []
    base = "SELECT c.* FROM clips c"
    if tag:
        base += (
            " JOIN clip_tags ct ON ct.clip_id = c.id"
            " JOIN tags t ON t.id = ct.tag_id"
        )
        where.append("t.name = ?")
        params.append(tag)
    if collection:
        where.append("c.collection = ?")
        params.append(collection)
    sql = base + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY c.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_clip_to_dict(conn, r) for r in rows]


def cloud_backup(conn: sqlite3.Connection) -> dict:
    """Build the cloud organizer's Restore/Sync payload: every Instagram reel
    with its collection + tags (shortcodes only — no files)."""
    reels: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT id, ig_shortcode, collection FROM clips "
        "WHERE ig_shortcode IS NOT NULL AND source='instagram'"
    ).fetchall():
        tags = [t["name"] for t in conn.execute(
            "SELECT t.name FROM tags t JOIN clip_tags ct ON ct.tag_id=t.id "
            "WHERE ct.clip_id=? ORDER BY t.name", (r["id"],)).fetchall()]
        reels[r["ig_shortcode"]] = {
            "code": r["ig_shortcode"], "tags": tags,
            "collection": r["collection"], "note": "",
        }
    return {"reels": reels}


def set_thumb_url(conn: sqlite3.Connection, shortcode: str, url: str) -> None:
    """Store the reel's remote cover-image URL (from the saved feed) so the grid
    can show a thumbnail without downloading anything. Refreshed each run because
    Instagram CDN URLs expire; skipped when empty so we never wipe a good one."""
    if not url:
        return
    conn.execute(
        "UPDATE clips SET thumb_url = ? WHERE ig_shortcode = ?",
        (url, shortcode),
    )


def set_collection_ids(conn: sqlite3.Connection, shortcode: str, ids: list) -> None:
    """Store the Instagram saved-collection ids a reel belongs to (from the feed)."""
    conn.execute(
        "UPDATE clips SET collection_ids = ? WHERE ig_shortcode = ?",
        (json.dumps(ids), shortcode),
    )


def collection_id_name_map(conn: sqlite3.Connection) -> dict:
    """Learn collection_id -> name from reels that already have BOTH a name and
    their collection ids (named in a past sync, ids from the current feed)."""
    mapping: dict = {}
    rows = conn.execute(
        "SELECT collection, collection_ids FROM clips "
        "WHERE collection IS NOT NULL AND collection <> '' AND collection_ids IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            ids = json.loads(r["collection_ids"]) or []
        except (TypeError, ValueError):
            ids = []
        for cid in ids:
            mapping.setdefault(str(cid), r["collection"])
    return mapping


def apply_collection_names(conn: sqlite3.Connection, id_name: dict) -> int:
    """Set collection name on reels that have collection ids but no name yet."""
    if not id_name:
        return 0
    n = 0
    rows = conn.execute(
        "SELECT id, collection_ids FROM clips "
        "WHERE (collection IS NULL OR collection = '') AND collection_ids IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            ids = json.loads(r["collection_ids"]) or []
        except (TypeError, ValueError):
            ids = []
        for cid in ids:
            if str(cid) in id_name:
                conn.execute("UPDATE clips SET collection = ? WHERE id = ?",
                             (id_name[str(cid)], r["id"]))
                n += 1
                break
    return n


def all_collections(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT collection FROM clips "
        "WHERE collection IS NOT NULL AND collection <> '' ORDER BY collection"
    ).fetchall()
    return [r["collection"] for r in rows]


def set_collection(
    conn: sqlite3.Connection, shortcode: str, collection: str,
    owner: str | None = None, caption: str | None = None,
) -> int:
    """Tag a clip with its collection; backfill owner/caption if still empty."""
    cur = conn.execute(
        """
        UPDATE clips
           SET collection = ?,
               ig_owner = COALESCE(NULLIF(ig_owner, ''), ?),
               caption  = COALESCE(NULLIF(caption, ''), ?)
         WHERE ig_shortcode = ?
        """,
        (collection, owner, caption, shortcode),
    )
    return cur.rowcount


def _clip_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    tags = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN clip_tags ct ON ct.tag_id = t.id
        WHERE ct.clip_id = ?
        ORDER BY t.name
        """,
        (row["id"],),
    ).fetchall()
    d = dict(row)
    d["tags"] = [t["name"] for t in tags]
    d["op"] = json.loads(row["op"]) if row["op"] else None
    d["segments"] = list_segments(conn, row["id"])
    return d


def add_tag(conn: sqlite3.Connection, clip_id: int, name: str) -> None:
    name = name.strip().lower()
    if not name:
        return
    conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
    tag = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id) VALUES (?, ?)",
        (clip_id, tag["id"]),
    )


def remove_tag(conn: sqlite3.Connection, clip_id: int, name: str) -> None:
    conn.execute(
        """
        DELETE FROM clip_tags
        WHERE clip_id = ?
          AND tag_id = (SELECT id FROM tags WHERE name = ?)
        """,
        (clip_id, name.strip().lower()),
    )


def all_tags(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
    return [r["name"] for r in rows]


# --------------------------------------------------------------- metadata ----
def update_metadata(conn: sqlite3.Connection, clip_id: int, fields: dict) -> None:
    """Update only the provided metadata columns (partial patch)."""
    allowed = {"title", "description"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    conn.execute(
        f"UPDATE clips SET {cols} WHERE id = ?", (*sets.values(), clip_id)
    )


# --------------------------------------------------------------- segments ----
def add_segment(
    conn: sqlite3.Connection,
    clip_id: int,
    start: float,
    end: float,
    label: str | None = None,
) -> int:
    cur = conn.execute(
        'INSERT INTO segments (clip_id, label, start, "end") VALUES (?, ?, ?, ?)',
        (clip_id, (label or "").strip() or None, start, end),
    )
    return cur.lastrowid


def list_segments(conn: sqlite3.Connection, clip_id: int) -> list[dict]:
    rows = conn.execute(
        'SELECT * FROM segments WHERE clip_id = ? ORDER BY start', (clip_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_segment(conn: sqlite3.Connection, segment_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM segments WHERE id = ?", (segment_id,)
    ).fetchone()


def delete_segment(conn: sqlite3.Connection, segment_id: int) -> None:
    conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
