"""Video operations backed by ffmpeg/ffprobe.

Everything shells out to the system ffmpeg binaries — the most reliable way to do
trim/concat/speed across codecs. Functions here are pure file-in/file-out; they
know nothing about the database. Callers persist the results.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import config


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(
            f"command failed: {' '.join(cmd)}\n{proc.stderr.strip()[-1000:]}"
        )


@dataclass
class Probe:
    width: int | None
    height: int | None
    duration: float | None
    fps: float | None


def probe(path: Path) -> Probe:
    """Read basic stream metadata from a video file."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    info = json.loads(proc.stdout or "{}")
    vstream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    width = height = fps = None
    if vstream:
        width = vstream.get("width")
        height = vstream.get("height")
        rate = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "0/0"
        try:
            num, den = rate.split("/")
            fps = round(float(num) / float(den), 3) if float(den) else None
        except (ValueError, ZeroDivisionError):
            fps = None
    duration = None
    if info.get("format", {}).get("duration"):
        try:
            duration = round(float(info["format"]["duration"]), 3)
        except ValueError:
            duration = None
    return Probe(width=width, height=height, duration=duration, fps=fps)


def make_thumbnail(video: Path, at_seconds: float = 1.0) -> Path:
    """Grab a single poster frame; returns path under THUMBS_DIR."""
    out = config.THUMBS_DIR / f"{video.stem}.jpg"
    _run([
        "ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video),
        "-frames:v", "1", "-q:v", "3", str(out),
    ])
    return out


def _derived_path(suffix: str = ".mp4") -> Path:
    return config.DERIVED_DIR / f"{uuid.uuid4().hex}{suffix}"


def trim(src: Path, start: float, end: float) -> Path:
    """Cut [start, end] (seconds). Re-encodes for frame-accurate cuts."""
    if end <= start:
        raise MediaError("end must be greater than start")
    out = _derived_path()
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-ss", str(start), "-to", str(end),
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
        str(out),
    ])
    return out


def set_speed(src: Path, factor: float) -> Path:
    """Change playback speed. factor>1 = faster, factor<1 = slower."""
    if factor <= 0:
        raise MediaError("speed factor must be positive")
    out = _derived_path()
    # video PTS scales by 1/factor; audio atempo handles 0.5x..2.0x per filter,
    # so chain filters for factors outside that range.
    atempo = _atempo_chain(factor)
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-filter_complex",
        f"[0:v]setpts={1/factor}*PTS[v];[0:a]{atempo}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
        str(out),
    ])
    return out


def _atempo_chain(factor: float) -> str:
    """atempo only accepts 0.5..2.0, so decompose larger factors into a chain."""
    remaining = factor
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def concat(sources: list[Path]) -> Path:
    """Join clips end to end. Normalizes each to a common format first so clips
    with different resolutions/codecs concatenate cleanly."""
    if len(sources) < 2:
        raise MediaError("concat needs at least two clips")
    out = _derived_path()
    inputs: list[str] = []
    filters: list[str] = []
    for i, src in enumerate(sources):
        inputs += ["-i", str(src)]
        # normalize to 1080-wide, 30fps, sar 1, with audio
        filters.append(
            f"[{i}:v]scale=1080:-2,setsar=1,fps=30[v{i}];"
            f"[{i}:a]aresample=44100[a{i}]"
        )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(sources)))
    filter_complex = (
        ";".join(filters)
        + f";{concat_inputs}concat=n={len(sources)}:v=1:a=1[v][a]"
    )
    _run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
        str(out),
    ])
    return out
