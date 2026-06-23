"""Reeler API — the thin end-to-end slice.

Routes cover every verb of the pipeline:
  sniff      POST /api/ingest
  visualize  GET  /api/clips, GET /api/clips/{id}/file (+ thumbs)
  tag        POST/DELETE /api/clips/{id}/tags
  edit       POST /api/clips/{id}/trim
  manipulate POST /api/clips/{id}/speed
  combine    POST /api/combine
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, instagram, jobs, media, repo

app = FastAPI(title="Reeler", version="0.1.0")

# Vite dev server runs on a different port; allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()
    # Catalogue any reels already on disk (e.g. from a prior/interrupted run)
    # in the background — purely local, no Instagram calls.
    jobs.scan_job.start(jobs.scan_worker)


# ---------------------------------------------------------------- models -----
class IngestRequest(BaseModel):
    limit: int = 12
    cookie_file: str | None = None
    username: str | None = None


class TagRequest(BaseModel):
    name: str


class TrimRequest(BaseModel):
    start: float
    end: float


class SpeedRequest(BaseModel):
    factor: float


class CaptionRequest(BaseModel):
    text: str
    position: str = "bottom"          # 'top' | 'center' | 'bottom'
    fontsize: int = 48
    start: float | None = None        # optional show window
    end: float | None = None


class CombineRequest(BaseModel):
    clip_ids: list[int]


class MetadataRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class SegmentRequest(BaseModel):
    start: float
    end: float
    label: str | None = None


class TimelineItem(BaseModel):
    kind: str                       # 'segment' | 'card'
    # segment
    clip_id: int | None = None
    start: float | None = None
    end: float | None = None
    # card
    text: str | None = None
    duration: float | None = 2.5
    bg: str | None = "black"


class TimelineRequest(BaseModel):
    items: list[TimelineItem]
    title: str | None = None


# ---------------------------------------------------------------- health -----
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": bool(media),
        "ig_cookie_configured": bool(config.IG_COOKIE_FILE),
    }


# ------------------------------------------------------- sniff / ingest ------
@app.get("/api/ig/status")
def ig_status() -> dict:
    """Check whether the configured Instagram session authenticates."""
    if not config.IG_COOKIE_FILE:
        return {"connected": False, "error": "no cookie file configured"}
    try:
        _, username = instagram.build_session()
        return {"connected": True, "username": username}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


@app.post("/api/sniff/start")
def sniff_start(req: IngestRequest) -> dict:
    """Begin a background crawl of the saved collection (skips existing)."""
    if not (config.IG_COOKIE_FILE or req.cookie_file):
        raise HTTPException(400, "no Instagram cookie configured")
    started = jobs.sniff_job.start(jobs.sniff_worker, req.cookie_file, req.username)
    if not started:
        raise HTTPException(409, "a sniff is already running")
    return jobs.sniff_job.status()


@app.post("/api/sniff/stop")
def sniff_stop() -> dict:
    """Ask the running crawl to stop after the current reel."""
    jobs.sniff_job.stop()
    return jobs.sniff_job.status()


@app.get("/api/sniff/progress")
def sniff_progress() -> dict:
    """Live progress of the crawl (poll this from the UI)."""
    return jobs.sniff_job.status()


@app.post("/api/collections/backfill")
def collections_backfill(req: IngestRequest) -> dict:
    """Map Instagram collections onto local clips (metadata only, no downloads)."""
    if not (config.IG_COOKIE_FILE or req.cookie_file):
        raise HTTPException(400, "no Instagram cookie configured")
    started = jobs.collections_job.start(
        jobs.collections_worker, req.cookie_file, req.username
    )
    if not started:
        raise HTTPException(409, "a collection backfill is already running")
    return jobs.collections_job.status()


@app.get("/api/collections/backfill/progress")
def collections_backfill_progress() -> dict:
    return jobs.collections_job.status()


@app.post("/api/library/scan")
def library_scan() -> dict:
    """Register reels already downloaded to disk — local only, no Instagram."""
    jobs.scan_job.start(jobs.scan_worker)
    return jobs.scan_job.status()


@app.get("/api/library/scan/progress")
def library_scan_progress() -> dict:
    return jobs.scan_job.status()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """Import a local video file — handy for testing the pipeline without IG."""
    config.ensure_dirs()
    dest = config.LIBRARY_DIR / file.filename
    with dest.open("wb") as fh:
        fh.write(await file.read())
    with db.get_conn() as conn:
        clip_id = repo.register_clip(conn, path=dest, source="upload")
        clip = repo._clip_to_dict(conn, repo.get_clip(conn, clip_id))
    return clip


# -------------------------------------------------------- visualize ----------
@app.get("/api/clips")
def list_clips(tag: str | None = None, collection: str | None = None) -> dict:
    with db.get_conn() as conn:
        return {
            "clips": repo.list_clips(conn, tag=tag, collection=collection),
            "tags": repo.all_tags(conn),
            "collections": repo.all_collections(conn),
        }


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: int) -> dict:
    with db.get_conn() as conn:
        row = repo.get_clip(conn, clip_id)
        if not row:
            raise HTTPException(404, "clip not found")
        return repo._clip_to_dict(conn, row)


@app.get("/api/clips/{clip_id}/file")
def clip_file(clip_id: int) -> FileResponse:
    with db.get_conn() as conn:
        row = repo.get_clip(conn, clip_id)
        if not row:
            raise HTTPException(404, "clip not found")
        return FileResponse(repo.clip_path(row), media_type="video/mp4")


@app.get("/api/clips/{clip_id}/thumb")
def clip_thumb(clip_id: int) -> FileResponse:
    with db.get_conn() as conn:
        row = repo.get_clip(conn, clip_id)
        if not row or not row["thumb_rel"]:
            raise HTTPException(404, "thumb not found")
        return FileResponse(config.DATA_DIR / row["thumb_rel"], media_type="image/jpeg")


# -------------------------------------------------------------- tag ----------
@app.post("/api/clips/{clip_id}/tags")
def add_tag(clip_id: int, req: TagRequest) -> dict:
    with db.get_conn() as conn:
        if not repo.get_clip(conn, clip_id):
            raise HTTPException(404, "clip not found")
        repo.add_tag(conn, clip_id, req.name)
        return repo._clip_to_dict(conn, repo.get_clip(conn, clip_id))


@app.delete("/api/clips/{clip_id}/tags/{name}")
def remove_tag(clip_id: int, name: str) -> dict:
    with db.get_conn() as conn:
        if not repo.get_clip(conn, clip_id):
            raise HTTPException(404, "clip not found")
        repo.remove_tag(conn, clip_id, name)
        return repo._clip_to_dict(conn, repo.get_clip(conn, clip_id))


# ----------------------------------------------- annotate (metadata) ---------
@app.patch("/api/clips/{clip_id}")
def update_metadata(clip_id: int, req: MetadataRequest) -> dict:
    with db.get_conn() as conn:
        if not repo.get_clip(conn, clip_id):
            raise HTTPException(404, "clip not found")
        repo.update_metadata(conn, clip_id, req.model_dump(exclude_unset=True))
        return repo._clip_to_dict(conn, repo.get_clip(conn, clip_id))


# ----------------------------------------------- segments (time-crop) --------
@app.post("/api/clips/{clip_id}/segments")
def add_segment(clip_id: int, req: SegmentRequest) -> dict:
    if req.end <= req.start:
        raise HTTPException(400, "end must be greater than start")
    with db.get_conn() as conn:
        if not repo.get_clip(conn, clip_id):
            raise HTTPException(404, "clip not found")
        repo.add_segment(conn, clip_id, req.start, req.end, req.label)
        return repo._clip_to_dict(conn, repo.get_clip(conn, clip_id))


@app.delete("/api/segments/{segment_id}")
def delete_segment(segment_id: int) -> dict:
    with db.get_conn() as conn:
        repo.delete_segment(conn, segment_id)
        return {"ok": True}


# ----------------------------------------------- timeline (combine) ----------
@app.post("/api/timeline")
def render_timeline(req: TimelineRequest) -> dict:
    if not req.items:
        raise HTTPException(400, "timeline has no items")
    with db.get_conn() as conn:
        resolved: list[dict] = []
        for it in req.items:
            if it.kind == "segment":
                if it.clip_id is None or it.start is None or it.end is None:
                    raise HTTPException(400, "segment item needs clip_id/start/end")
                row = repo.get_clip(conn, it.clip_id)
                if not row:
                    raise HTTPException(404, f"clip {it.clip_id} not found")
                resolved.append({
                    "kind": "segment", "path": repo.clip_path(row),
                    "start": it.start, "end": it.end,
                })
            elif it.kind == "card":
                resolved.append({
                    "kind": "card", "text": it.text or "",
                    "duration": it.duration or 2.5, "bg": it.bg or "black",
                })
            else:
                raise HTTPException(400, f"unknown item kind: {it.kind}")
        try:
            out = media.render_timeline(resolved)
        except media.MediaError as exc:
            raise HTTPException(400, str(exc))
        op = {"type": "timeline", "items": [i.model_dump() for i in req.items]}
        new_id = repo.register_clip(conn, path=out, source="derived", op=op)
        if req.title:
            repo.update_metadata(conn, new_id, {"title": req.title})
        return repo._clip_to_dict(conn, repo.get_clip(conn, new_id))


# ----------------------------------------------- edit / manipulate -----------
def _derive(clip_id: int, op_name: str, run, op_meta: dict) -> dict:
    with db.get_conn() as conn:
        row = repo.get_clip(conn, clip_id)
        if not row:
            raise HTTPException(404, "clip not found")
        try:
            out = run(repo.clip_path(row))
        except media.MediaError as exc:
            raise HTTPException(400, str(exc))
        new_id = repo.register_clip(
            conn, path=out, source="derived",
            op={"type": op_name, "parent": clip_id, **op_meta},
        )
        return repo._clip_to_dict(conn, repo.get_clip(conn, new_id))


@app.post("/api/clips/{clip_id}/trim")
def trim(clip_id: int, req: TrimRequest) -> dict:
    return _derive(
        clip_id, "trim",
        lambda p: media.trim(p, req.start, req.end),
        {"start": req.start, "end": req.end},
    )


@app.post("/api/clips/{clip_id}/speed")
def speed(clip_id: int, req: SpeedRequest) -> dict:
    return _derive(
        clip_id, "speed",
        lambda p: media.set_speed(p, req.factor),
        {"factor": req.factor},
    )


@app.post("/api/clips/{clip_id}/caption")
def caption(clip_id: int, req: CaptionRequest) -> dict:
    if not req.text.strip():
        raise HTTPException(400, "caption text is empty")
    return _derive(
        clip_id, "caption",
        lambda p: media.overlay_text(
            p, req.text, req.position, req.fontsize, req.start, req.end,
        ),
        {"text": req.text, "position": req.position, "fontsize": req.fontsize,
         "start": req.start, "end": req.end},
    )


# ----------------------------------------------------------- combine ---------
@app.post("/api/combine")
def combine(req: CombineRequest) -> dict:
    if len(req.clip_ids) < 2:
        raise HTTPException(400, "combine needs at least two clip ids")
    with db.get_conn() as conn:
        paths: list[Path] = []
        for cid in req.clip_ids:
            row = repo.get_clip(conn, cid)
            if not row:
                raise HTTPException(404, f"clip {cid} not found")
            paths.append(repo.clip_path(row))
        try:
            out = media.concat(paths)
        except media.MediaError as exc:
            raise HTTPException(400, str(exc))
        new_id = repo.register_clip(
            conn, path=out, source="derived",
            op={"type": "concat", "parents": req.clip_ids},
        )
        return repo._clip_to_dict(conn, repo.get_clip(conn, new_id))


# --------------------------------------------- serve built frontend ----------
# In production the Vite build lands in frontend/dist; mount it if present.
_DIST = config.REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
