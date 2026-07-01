"""Export the local Reeler library to a backup file the cloud organizer can
Restore — carrying shortcodes, collections, and tags. No Instagram calls.

Run (Windows), pointing at wherever your data lives:
    $env:REELER_DATA_DIR="F:\\Users\\mxgld\\reeler\\data"
    .venv\\Scripts\\python scripts\\export_cloud.py

It writes reeler-cloud-backup.json next to where you run it. Then in the cloud
app (https://brainpulp.github.io/reeler/) click "Restore" and pick that file.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

data_dir = Path(os.environ.get("REELER_DATA_DIR", "data"))
db_path = data_dir / "reeler.db"
if not db_path.exists():
    raise SystemExit(f"reeler.db not found at {db_path} — set REELER_DATA_DIR")

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row

reels: dict[str, dict] = {}
rows = con.execute(
    "SELECT id, ig_shortcode, collection FROM clips "
    "WHERE ig_shortcode IS NOT NULL AND source = 'instagram'"
).fetchall()
for r in rows:
    code = r["ig_shortcode"]
    tags = [
        t["name"]
        for t in con.execute(
            "SELECT t.name FROM tags t JOIN clip_tags ct ON ct.tag_id = t.id "
            "WHERE ct.clip_id = ? ORDER BY t.name",
            (r["id"],),
        ).fetchall()
    ]
    reels[code] = {
        "code": code,
        "tags": tags,
        "collection": r["collection"],
        "note": "",
    }

out = Path("reeler-cloud-backup.json")
out.write_text(json.dumps({"reels": reels}, indent=2), encoding="utf-8")

with_coll = sum(1 for v in reels.values() if v["collection"])
colls = sorted({v["collection"] for v in reels.values() if v["collection"]})
print(f"Wrote {len(reels)} reels to {out.resolve()}")
print(f"  {with_coll} have a collection across: {', '.join(colls) or '(none)'}")
print("Now: open the cloud app, click Restore, and choose this file.")
