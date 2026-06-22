"""Populate the library with sample clips so the UI is explorable without
Instagram. Generates a handful of short videos with ffmpeg, registers them as
if sniffed (owner + caption), adds tags/segments, and renders one timeline so a
derived clip shows up too.

Run from the backend/ dir:  python seed.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app import config, db, media, repo

SAMPLES = [
    # (ffmpeg lavfi source, size, seconds, owner, caption, tags)
    ("testsrc2", "1080x1920", 6, "wanderlust", "Sunrise over the dunes 🌅 #travel", ["travel", "nature"]),
    ("smptebars", "1080x1920", 5, "chef.lia", "30-second pasta hack you need", ["food", "howto"]),
    ("mandelbrot", "1080x1920", 7, "studio.motion", "Fractal loop, sound on 🔊", ["art", "loop"]),
    ("rgbtestsrc", "1080x1920", 4, "pets.daily", "He does this every morning 😂", ["funny", "pets"]),
    ("testsrc", "720x1280", 5, "gym.notes", "Form check: deadlift cues", ["fitness", "howto"]),
    ("yuvtestsrc", "1080x1920", 6, "city.frames", "Blue hour, downtown", ["travel", "night"]),
]


def make_video(source: str, size: str, seconds: int, out: Path) -> None:
    # Drive duration with -t so sources that don't take a `duration=` option
    # (e.g. mandelbrot) work the same as those that do.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"{source}=size={size}:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=300",
            "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(out),
        ],
        check=True, capture_output=True,
    )


def main() -> None:
    config.ensure_dirs()
    db.init_db()
    print(f"Seeding into {config.DATA_DIR}")

    first_two: list[int] = []
    with db.get_conn() as conn:
        for i, (src, size, secs, owner, caption, tags) in enumerate(SAMPLES):
            shortcode = f"SAMPLE{i:03d}"
            existing = conn.execute(
                "SELECT id FROM clips WHERE ig_shortcode = ?", (shortcode,)
            ).fetchone()
            if existing:
                print(f"  skip {shortcode} (already seeded)")
                continue
            path = config.LIBRARY_DIR / f"{shortcode}.mp4"
            make_video(src, size, secs, path)
            clip_id = repo.register_clip(
                conn, path=path, source="instagram",
                ig_shortcode=shortcode, ig_owner=owner, caption=caption,
            )
            for t in tags:
                repo.add_tag(conn, clip_id, t)
            # a couple of marked segments on each clip
            repo.add_segment(conn, clip_id, 0.5, min(2.5, secs - 0.5), "highlight")
            print(f"  + {owner}: {caption[:40]}")
            if len(first_two) < 2:
                first_two.append(clip_id)

    # Render one timeline (title card + two highlights) to show a derived clip.
    if len(first_two) == 2:
        with db.get_conn() as conn:
            paths = [repo.clip_path(repo.get_clip(conn, cid)) for cid in first_two]
            items = [
                {"kind": "card", "text": "My Montage", "duration": 1.5, "bg": "navy"},
                {"kind": "segment", "path": paths[0], "start": 0.5, "end": 2.0},
                {"kind": "segment", "path": paths[1], "start": 0.5, "end": 2.0},
            ]
            out = media.render_timeline(items)
            new_id = repo.register_clip(
                conn, path=out, source="derived",
                op={"type": "timeline", "seeded": True},
            )
            repo.update_metadata(conn, new_id, {"title": "My Montage (sample)"})
            print("  + rendered sample montage")

    print("Done. Start the app with ./scripts/dev.sh and open http://localhost:5173")


if __name__ == "__main__":
    main()
