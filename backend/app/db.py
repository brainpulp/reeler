"""SQLite access layer.

Deliberately thin: a single connection helper plus schema bootstrap. The schema
covers the whole thin-slice pipeline — clips (both originals and derived), tags,
and the many-to-many join between them.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,            -- 'instagram' | 'derived' | 'upload'
    ig_shortcode TEXT,                     -- Instagram shortcode, when source='instagram'
    ig_owner     TEXT,                     -- original poster's handle
    caption      TEXT,
    filename     TEXT NOT NULL,            -- basename on disk
    rel_path     TEXT NOT NULL,            -- path relative to DATA_DIR
    width        INTEGER,
    height       INTEGER,
    duration     REAL,                     -- seconds
    fps          REAL,
    thumb_rel    TEXT,                     -- thumbnail path relative to DATA_DIR
    op           TEXT,                     -- how a derived clip was produced (json)
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_clips_shortcode
    ON clips(ig_shortcode) WHERE ig_shortcode IS NOT NULL;

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS clip_tags (
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (clip_id, tag_id)
);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
