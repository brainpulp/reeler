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

from . import config, db, instagram, media, repo

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


class CombineRequest(BaseModel):
    clip_ids: list[int]


# ---------------------------------------------------------------- health -----
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": bool(media),
        "ig_cookie_configured": bool(config.IG_COOKIE_FILE),
    }


# ------------------------------------------------------- sniff / ingest ------
@app.post("/api/ingest")
def ingest(req: IngestRequest) -> dict:
    """Fetch saved Instagram videos into the local library."""
    try:
        loader, username = instagram.build_session(req.cookie_file, req.username)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    added: list[dict] = []
    with db.get_conn() as conn:
        for post in instagram.iter_saved(loader, username, limit=req.limit):
            try:
                path = instagram.download_video(loader, post, config.LIBRARY_DIR)
            except Exception as exc:  # network/availability hiccups per-post
                continue
            clip_id = repo.register_clip(
                conn, path=path, source="instagram",
                ig_shortcode=post.shortcode, ig_owner=post.owner,
                caption=post.caption,
            )
            added.append({"id": clip_id, "shortcode": post.shortcode})
    return {"added": added, "count": len(added)}


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
def list_clips(tag: str | None = None) -> dict:
    with db.get_conn() as conn:
        return {
            "clips": repo.list_clips(conn, tag=tag),
            "tags": repo.all_tags(conn),
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
