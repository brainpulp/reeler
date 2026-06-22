# 🎬 Reeler

A personal, local tool to **sniff, visualize, tag, combine, edit, and
manipulate** the videos you've saved on your own Instagram account.

Everything runs on your machine. Reeler reads *your* Saved collection using a
session you're already logged into, archives the videos locally, and gives you a
small studio to organize and rework them. It is for personal, local archival of
content your account can already access — no scraping at scale, no password
handling, no anti-detection.

## Pipeline

| Stage | What it does |
|-------|--------------|
| **Sniff** | Pull saved reels into a local library via your browser session |
| **Visualize** | Browse a grid of thumbnails, click to play |
| **Annotate** | Per-clip title + description, plus free-text tags; filter by tag |
| **Time-crop** | Mark labeled time-segments inside a clip (the reusable combine units) |
| **Combine** | Assemble an ordered **timeline** of segments + text cards → new clip |
| **Edit** | Trim a clip to in/out points → new derived clip |
| **Caption** | Burn on-screen text onto a clip (optionally for a time window) |
| **Manipulate** | Change playback speed (the pattern for further transforms) |

**Text cards** ("inner screens") are full-canvas screens of centered text you
can drop between segments on the timeline. Everything is conformed to a shared
1080×1920 canvas (letterboxed, never distorted) so clips of any aspect ratio
combine cleanly.

Edits never overwrite originals — each operation produces a new *derived* clip,
so the library is non-destructive.

## Stack

- **Backend:** Python + FastAPI, SQLite for metadata/tags, `ffmpeg` for video ops
- **Ingestion:** [`instaloader`](https://instaloader.github.io/) with an imported browser session
- **Frontend:** React + Vite

## Requirements

- Python 3.11+, Node 18+, and **ffmpeg** (`ffmpeg`/`ffprobe` on your PATH)

## Quick start

```bash
cp .env.example .env      # then edit it (see "Instagram session" below)
./scripts/dev.sh          # backend on :8000, UI on :5173
```

Open http://localhost:5173.

Don't have the session wired up yet? You can still try the whole pipeline:
click **Import file** to add a local video, then tag / trim / speed / combine it.

## Instagram session (for "Sniff")

Reeler never sees your password. Instead:

1. Log into Instagram in your browser.
2. Export cookies for `instagram.com` in **Netscape `cookies.txt`** format
   (e.g. the "Get cookies.txt LOCALLY" browser extension).
3. Point `REELER_IG_COOKIE_FILE` at that file and set `REELER_IG_USERNAME`
   in your `.env`.
4. Click **Sniff saved reels** in the UI (or `POST /api/ingest`).

The cookie file and the `data/` directory are gitignored.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/ingest` | Fetch saved videos into the library |
| `POST` | `/api/upload` | Import a local video file |
| `GET`  | `/api/clips?tag=` | List clips (optionally filtered by tag) |
| `GET`  | `/api/clips/{id}/file` | Stream the video |
| `GET`  | `/api/clips/{id}/thumb` | Poster thumbnail |
| `PATCH`| `/api/clips/{id}` | Update `{title, description}` annotation |
| `POST` / `DELETE` | `/api/clips/{id}/tags[/{name}]` | Add / remove a tag |
| `POST` | `/api/clips/{id}/segments` | Mark `{start, end, label}` time-segment |
| `DELETE` | `/api/segments/{id}` | Delete a segment |
| `POST` | `/api/timeline` | Render ordered `{items: [...]}` of segments + cards |
| `POST` | `/api/clips/{id}/trim` | Trim `{start, end}` → derived clip |
| `POST` | `/api/clips/{id}/speed` | Speed `{factor}` → derived clip |
| `POST` | `/api/clips/{id}/caption` | Burn in `{text, position, start?, end?}` → derived clip |
| `POST` | `/api/combine` | Concat `{clip_ids: [...]}` whole clips → derived clip |

A timeline item is either
`{"kind":"segment","clip_id":N,"start":S,"end":E}` or
`{"kind":"card","text":"...","duration":D,"bg":"black"}`.

## Project layout

```
backend/app/
  main.py        FastAPI routes (the pipeline)
  instagram.py   session import + saved-posts fetch (sniff)
  media.py       ffmpeg ops: probe, thumbnail, trim, speed, concat
  repo.py        files <-> SQLite clip rows
  db.py          schema + connection
  config.py      paths & env
frontend/src/
  App.jsx        library grid, ingest/upload, combine
  ClipDetail.jsx player + tag/trim/speed editor
```

## Notes & limits

- `instaloader` ingestion couldn't be exercised in CI (no live account); the
  media pipeline and all API routes are tested end-to-end against generated
  videos.
- This tool is for your own saved content and personal use. Respect Instagram's
  terms and the rights of original creators.
