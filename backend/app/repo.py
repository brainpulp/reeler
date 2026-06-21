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
) -> int:
    """Probe + thumbnail a file already on disk and insert a clip row."""
    info = media.probe(path)
    try:
        thumb = media.make_thumbnail(path)
        thumb_rel = _rel(thumb)
    except media.MediaError:
        thumb_rel = None

    values = (
        source, ig_shortcode, ig_owner, caption, path.name, _rel(path),
        info.width, info.height, info.duration, info.fps, thumb_rel,
        json.dumps(op) if op else None,
    )
    cols = (
        "(source, ig_shortcode, ig_owner, caption, filename, rel_path, "
        "width, height, duration, fps, thumb_rel, op)"
    )
    if ig_shortcode is None:
        # Uploads and derived clips have no shortcode: plain insert.
        cur = conn.execute(
            f"INSERT INTO clips {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", values
        )
        return cur.lastrowid

    # Instagram clips: re-ingesting the same shortcode refreshes its caption.
    # The conflict target must name the partial unique index's predicate.
    conn.execute(
        f"""
        INSERT INTO clips {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ig_shortcode) WHERE ig_shortcode IS NOT NULL
        DO UPDATE SET caption = excluded.caption
        """,
        values,
    )
    row = conn.execute(
        "SELECT id FROM clips WHERE ig_shortcode = ?", (ig_shortcode,)
    ).fetchone()
    return row["id"]


def get_clip(conn: sqlite3.Connection, clip_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()


def clip_path(row: sqlite3.Row) -> Path:
    return config.DATA_DIR / row["rel_path"]


def list_clips(conn: sqlite3.Connection, tag: str | None = None) -> list[dict]:
    if tag:
        rows = conn.execute(
            """
            SELECT c.* FROM clips c
            JOIN clip_tags ct ON ct.clip_id = c.id
            JOIN tags t ON t.id = ct.tag_id
            WHERE t.name = ?
            ORDER BY c.created_at DESC
            """,
            (tag,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clips ORDER BY created_at DESC"
        ).fetchall()
    return [_clip_to_dict(conn, r) for r in rows]


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
def update_metadata(
    conn: sqlite3.Connection,
    clip_id: int,
    title: str | None,
    description: str | None,
) -> None:
    conn.execute(
        "UPDATE clips SET title = ?, description = ? WHERE id = ?",
        (title, description, clip_id),
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
