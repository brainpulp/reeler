# CLAUDE.md — Reeler

Personal local tool to sniff, browse, tag, clip, caption, and combine the
videos saved in the owner's Instagram account. Single-user, local, personal
archival of the owner's own saved content. **Do not** add scale scraping,
anti-detection, or anything that hammers Instagram.

---

## ⚠️ READ FIRST — current real-world state (June 2026)

This project is **already running successfully** on the owner's Windows PC.
A lot was learned getting there; don't re-derive it.

- **OS:** Windows 11. Repo at `C:\Users\mxgld\reeler`.
- **Python:** the system Python is **3.14** (very new). Deps are pinned to work
  with it — see "Gotchas". The venv is `.venv` in the repo root
  (`.venv\Scripts\python`, Windows layout — NOT `bin/`).
- **ffmpeg:** installed and on PATH.
- **Instagram cookie:** `F:\downloads\www.instagram.com_cookies.txt`
  (Netscape cookies.txt with `sessionid` + `csrftoken`). Never commit it.
- **Data dir:** `F:\Users\mxgld\reeler\data` (set via `REELER_DATA_DIR` in
  `RUN-REELER.bat`). Contains `library/` (the .mp4s), `derived/`, `thumbs/`,
  and `reeler.db`. (Moved here from C: — Task 1 done.)
- **Already downloaded:** ~**309 reels** in `C:\Users\mxgld\reeler\data\library`,
  named `{shortcode}.mp4`. They are catalogued into the DB by the startup
  "library scan" (filename = Instagram shortcode).
- **Launcher:** `RUN-REELER.bat` in the repo root (gitignored / generated) sets
  the two env vars and starts backend (:8000) + frontend (:5173) + opens the
  browser. The owner double-clicks it to run. A canonical version lives at
  `scripts\dev.bat`.

To run during development on this machine:
```bat
set REELER_IG_COOKIE_FILE=F:\downloads\www.instagram.com_cookies.txt
set REELER_DATA_DIR=C:\Users\mxgld\reeler\data
.venv\Scripts\python -m uvicorn --app-dir backend app.main:app --port 8000
REM separate window:
cd frontend && npm run dev
```

---

## Architecture

- **Backend:** Python + FastAPI (`backend/app/`), SQLite, `ffmpeg`/`ffprobe`
  shelled out for all video ops.
- **Frontend:** React + Vite (`frontend/src/`).
- **Ingestion:** authenticated session built with `instaloader` (cookies only),
  but saved posts are fetched via Instagram's **current private web API**
  directly — instaloader's `get_saved_posts()` uses a dead GraphQL hash.

Backend files:
- `config.py` — paths & env (`REELER_DATA_DIR`, `REELER_IG_COOKIE_FILE`). All
  clip paths in the DB are stored **relative to `DATA_DIR`** (`rel_path`), so the
  whole `data/` folder can be moved as long as `REELER_DATA_DIR` follows it.
- `db.py` — schema + WAL/busy_timeout. Tables: `clips`, `tags`, `clip_tags`,
  `segments`.
- `instagram.py` — `build_session` (cookie import + CSRF header + fast timeouts),
  `iter_saved` (private web API `/api/v1/feed/saved/posts/`, paginated),
  `download_video`.
- `media.py` — probe, thumbnail, trim, speed, concat, text cards, caption
  burn-in; everything normalized to a 1080x1920 canvas for combining.
- `repo.py` — files <-> clip rows, tags, segments, metadata, `shortcode_exists`.
- `jobs.py` — generic background `Job` + `sniff_worker` and `scan_worker`
  (daemon threads, pollable progress, cancellable).
- `main.py` — API routes.

Key API routes: `/api/clips`, `/api/clips/{id}/{file,thumb}`,
`/api/clips/{id}` (PATCH title/description), `/api/clips/{id}/tags`,
`/api/clips/{id}/segments`, `/api/clips/{id}/{trim,speed,caption}`,
`/api/timeline`, `/api/ig/status`, `/api/sniff/{start,stop,progress}`,
`/api/library/scan` (+ `/progress`), `/api/upload`.

---

## 🎯 PENDING TASKS (what the owner wants next)

### Task 1 — Move the library from C: to F: ✅ DONE
Data now lives at `F:\Users\mxgld\reeler\data`; `RUN-REELER.bat` sets
`REELER_DATA_DIR` accordingly. Moved with `robocopy /MOVE` (more robust than
Move-Item across drives). Lesson: kill all `python.exe`/`node.exe` first so the
DB isn't locked, and the **launcher's `REELER_DATA_DIR` line must actually point
at F:** — a stale C: path silently makes the grid empty (`scan` sees 0 files).

### Task 2 — Organize reels by Instagram collection ✅ BUILT (run backfill gently)
Implemented as **grid grouping** (the owner's choice — a collection filter bar,
no files moved). Run it via the **"Organize by collection"** button (or
`POST /api/collections/backfill`); it's a paced, cancellable, **metadata-only**
background job (`collections_worker`) that maps each named collection's reels
onto local clips and backfills `collection`/owner/caption — **no video
downloads**. Filter the grid with `GET /api/clips?collection=NAME`.

Run it **after the account has rested** from the burst, and treat it like a
sniff (one paced run, abort-and-wait on errors). Endpoint shapes
(`/api/v1/collections/list/`, `/api/v1/feed/collection/{id}/posts/`) are coded
defensively but unverified against a live account — if they 've drifted, the
job will surface a clear error; adjust `instagram.list_collections` /
`iter_collection_posts`.

Still open / optional follow-ups:
- Make the **sniff** collection-aware so *future* pulls record collection
  directly (iterate per-collection feeds, or re-run the backfill after a sniff).
- Optional: physical `library/{collection}/` folders (owner chose UI grouping
  for now; would need `rel_path` updates in the same transaction).

**Important provenance reality:** the 309 already-downloaded files carry only
their **shortcode** (the filename). Collection, owner, and caption were NOT
captured (the saved-posts feed returns everything flat). The shortcode is enough
to map each file back to its collection **without re-downloading any video** —
do it with metadata-only calls.

Suggested implementation:
1. **Fetch collections** via the private web API (reuse the authenticated
   `loader.context._session` with header `X-IG-App-ID: 936619743392459`):
   - List: `GET https://www.instagram.com/api/v1/collections/list/`
     → collections with `collection_id` + `collection_name`.
   - Per collection: `GET https://www.instagram.com/api/v1/feed/collection/{collection_id}/posts/?max_id=...`
     → `items[].media` with `code` (shortcode), `user`, `caption`.
   - These shapes may have drifted — verify the JSON at runtime and code
     defensively (the saved-posts endpoint needed the same treatment).
2. **Backfill** existing clips: build a shortcode → collection map from the
   collection feeds, and set the collection (and backfill owner/caption while
   you have them) on existing rows. **No video downloads** in this step.
3. **Schema:** add a `collection` column to `clips` (idempotent migration like
   the `title`/`description` one in `db.py`).
4. **Folders:** decide between (a) UI grouping/filter by collection (like the
   tag bar — lower risk, no file moves) and/or (b) physically moving files into
   `library/{collection}/{shortcode}.mp4` (update `rel_path` in the DB in the
   same transaction). UI grouping is recommended first; physical folders
   optional. Confirm the owner's preference.
5. **Make the sniff collection-aware** so future pulls record each reel's
   collection (iterate per-collection feeds, or map shortcodes after the flat
   sniff).

**Safety for both:** pace Instagram requests (~1s), reuse the existing
`Job`/progress/stop pattern for any crawl, and never re-download a video that's
already on disk (`scan_worker`/`sniff_worker` already skip by shortcode and by
file-on-disk).

---

## 🛡️ Instagram safety & sniff scheduling (POLICY — follow strictly)

The owner has **1000+ saved videos** and already triggered one accidental burst
that risked a temporary action-block. Protecting the account is a hard
requirement. **Never** trade this away for speed.

**Enforced in code (`jobs.py`) — do not weaken:**
- **Per-run cap:** `MAX_NEW_PER_RUN = 150` network downloads. One sniff run can
  never become a large burst. Reels already on disk are registered for free and
  don't count.
- **Jittered pacing:** `random.uniform(1.5, 3.0)s` between *real* downloads only.
- **Cancellable:** the Stop button / `sniff_job.stop()` halts after the current
  reel. Long jobs run server-side, so this is the only safe stop.
- **Abort on trouble:** `iter_saved` raises on non-200 / empty-JSON (rate-limit
  signals); the job records the error and stops. Treat any such error as a
  rate-limit and back off.

**Scheduling rules (follow these; bake into any scheduler you build):**
1. **One sniff run per day, max.** Do not chain runs to drain the library
   faster. At 150/day the ~1000 backlog fills in about a week — that's fine.
2. **Minimum 24h between runs.** A scheduler must enforce this interval.
3. **After any error/rate-limit, wait ≥24h** before the next attempt. After a
   known burst (like today's), wait 24–48h before sniffing at all.
4. **Routine cadence: weekly.** Re-sniff skips everything already saved and only
   pulls new reels (small, fast), so the weekly job is light. Never more often
   than weekly for routine use.
5. **Never auto-run a sniff unattended without the cap + pacing + interval
   checks.** The only thing that auto-runs on startup is the **local disk scan**
   (`scan_worker`) — it makes **zero Instagram calls** and is always safe.
6. **Backfilling collections (Task 2)** uses the same discipline: paced,
   cancellable, metadata-only (no video downloads), abort-and-wait on errors.

If you add a real scheduler (e.g. weekly), implement it as: check "last run
≥ interval ago AND no recent error", run one capped sniff, record the
timestamp/outcome, then wait. Surface it in the UI and keep the Stop button.

## Gotchas / lessons learned (don't repeat these)

- **Python 3.14:** `pydantic`/`uvicorn[standard]` had no wheels and tried to
  compile (Rust/PyO3) and failed. Fixed by pinning `pydantic>=2.11,<3` and using
  plain `uvicorn` (no `[standard]`). See `backend/requirements.txt`.
- **macOS system Python is 3.9**; `eval_type_backport` is included so pydantic
  can evaluate `X | None` there. `dev.sh` prefers 3.11–3.13.
- **Saved posts:** instaloader's `get_saved_posts()` (all versions incl. 4.15.1)
  uses a retired GraphQL hash → empty/non-JSON. We call
  `/api/v1/feed/saved/posts/` directly with `X-IG-App-ID`. Expect Instagram to
  change endpoints; fail with clear messages.
- **CSRF:** an imported cookie session must set the `X-CSRFToken` header from the
  `csrftoken` cookie or authenticated calls 403. `build_session` does this.
- **Timeouts:** instaloader defaults to a 300s request timeout — capped to 20s
  and `max_connection_attempts=1` so auth failures are fast, not hangs.
- **Rate limiting:** the owner has **1000+ saved videos**. A burst download
  risks a temporary Instagram action-block. The sniff is a **cancellable
  background job paced ~1s/download** with a Stop button. Pull big libraries
  gradually. Never remove the pacing or the stop control.
- **Long jobs run server-side**, not in the browser — closing the tab does NOT
  stop them. That's why there's a Stop button + cancellable jobs.
- **Windows quirks:** venv scripts live in `.venv\Scripts` (not `bin`); the
  browser hitting `localhost:8000` directly may time out behind a VPN, but the
  app's Vite proxy (`:5173/api/...`) works. `.env` parsing in batch was flaky —
  the launcher sets env vars explicitly with `set` instead.
- **DB paths are relative to `DATA_DIR`** — moving `data/` is safe if
  `REELER_DATA_DIR` moves with it.

## Conventions

- Edits are non-destructive: trim/speed/caption/timeline produce new "derived"
  clips; originals are untouched.
- Verify changes by actually running ffmpeg / the API, not just by reading code.
- Keep secrets (cookie file) and `data/` out of git (already gitignored).
