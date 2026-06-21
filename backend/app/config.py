"""Central configuration and on-disk layout for Reeler.

All persistent state lives under ``data/`` at the repo root, which is
gitignored. Nothing here should ever hold a committed secret — the Instagram
session is loaded from a cookie file the user points us at, not from the repo.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root is two levels up from this file: backend/app/config.py -> repo/
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("REELER_DATA_DIR", REPO_ROOT / "data"))
LIBRARY_DIR = DATA_DIR / "library"      # original downloaded videos
DERIVED_DIR = DATA_DIR / "derived"      # outputs of edit/combine/manipulate
THUMBS_DIR = DATA_DIR / "thumbs"        # generated poster frames
DB_PATH = DATA_DIR / "reeler.db"

# Where the user's exported Instagram session cookies live. Optional: ingestion
# only needs it when actually fetching from Instagram.
IG_COOKIE_FILE = os.environ.get("REELER_IG_COOKIE_FILE", "")
IG_USERNAME = os.environ.get("REELER_IG_USERNAME", "")


def ensure_dirs() -> None:
    for d in (DATA_DIR, LIBRARY_DIR, DERIVED_DIR, THUMBS_DIR):
        d.mkdir(parents=True, exist_ok=True)
