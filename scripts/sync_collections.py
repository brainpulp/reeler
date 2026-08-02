"""One-shot Instagram → cloud sync for collections. METADATA ONLY — never
downloads a video, just reads which reels are in which collection and writes
reeler-cloud-backup.json for the cloud app.

Run (do this every few days as you add reels to collections):
    $env:REELER_DATA_DIR="F:\\Users\\mxgld\\reeler\\data"
    .venv\\Scripts\\python scripts\\sync_collections.py

It's paced to be gentle on Instagram; press Ctrl+C to stop anytime. When it
finishes, open the cloud app and click "Import / Sync" on the json it wrote.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config, db, instagram, repo  # noqa: E402

config.ensure_dirs()
db.init_db()

print("Connecting to Instagram…")
loader, uname = instagram.build_session()
print(f"Signed in as @{uname}")

collections = instagram.list_collections(loader)
print(f"Found {len(collections)} collections")


def planned(sc: str) -> str:
    return str((config.LIBRARY_DIR / f"{sc}.mp4").relative_to(config.DATA_DIR))


total = 0
with db.get_conn() as conn:
    for coll in collections:
        n = 0
        for post in instagram.iter_collection_posts(loader, coll["id"]):
            if not repo.shortcode_exists(conn, post.shortcode):
                repo.register_indexed(
                    conn, shortcode=post.shortcode, media_id=post.media_id,
                    owner=post.owner, caption=post.caption,
                    thumb_rel=None, planned_rel=planned(post.shortcode),
                )
            repo.set_collection(conn, post.shortcode, coll["name"],
                                post.owner, post.caption)
            conn.commit()
            n += 1
            total += 1
            time.sleep(0.5)  # gentle pacing (metadata only)
        print(f"  {coll['name']}: {n}")
        time.sleep(1.0)

# Write the cloud backup (all instagram reels + their collections + tags).
reels: dict[str, dict] = {}
with db.get_conn() as conn:
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

out = Path("reeler-cloud-backup.json")
out.write_text(json.dumps({"reels": reels}, indent=2), encoding="utf-8")
with_coll = sum(1 for v in reels.values() if v["collection"])
print(f"\nCataloged {total} reels across collections.")
print(f"Wrote {len(reels)} reels ({with_coll} in a collection) to {out.resolve()}")
print("Now: open the cloud app and click 'Import / Sync' on that file.")
