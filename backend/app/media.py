"""Video operations backed by ffmpeg/ffprobe.

Everything shells out to the system ffmpeg binaries — the most reliable way to do
trim/concat/speed across codecs. Functions here are pure file-in/file-out; they
know nothing about the database. Callers persist the results.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import config

# Output canvas everything is normalized to (portrait 9:16, the reel default).
CANVAS_W = 1080
CANVAS_H = 1920
CANVAS_FPS = 30
AUDIO_RATE = 44100

# Font used for text cards. Picked from a few common locations so this works
# across distros without extra config.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _font() -> str:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    raise MediaError("no usable TTF font found for text cards")


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


# Video normalization: fit any clip inside the canvas without distortion
# (letterbox-pad), so segments and cards of any aspect ratio concatenate cleanly.
_NORM_VF = (
    f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,"
    f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
    f"fps={CANVAS_FPS},format=yuv420p"
)


def concat(sources: list[Path]) -> Path:
    """Join clips end to end, normalizing each to the shared canvas first so
    clips with different resolutions/codecs concatenate cleanly."""
    if len(sources) < 2:
        raise MediaError("concat needs at least two clips")
    out = _derived_path()
    inputs: list[str] = []
    filters: list[str] = []
    for i, src in enumerate(sources):
        inputs += ["-i", str(src)]
        filters.append(
            f"[{i}:v]{_NORM_VF}[v{i}];[{i}:a]aresample={AUDIO_RATE}[a{i}]"
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


def _has_audio(path: Path) -> bool:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    return bool(proc.stdout.strip())


def normalize_segment(src: Path, start: float, end: float, out: Path) -> Path:
    """Cut [start, end] and conform it to the canvas. Synthesizes silent audio
    for clips that have none so every part has a uniform stream layout."""
    if end <= start:
        raise MediaError("segment end must be greater than start")
    duration = end - start
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(src), "-t", str(duration)]
    if _has_audio(src):
        amap = "0:a"
    else:
        cmd += ["-f", "lavfi", "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}"]
        amap = "1:a"
    cmd += [
        "-vf", _NORM_VF, "-map", "0:v", "-map", amap, "-shortest",
        "-c:v", "libx264", "-c:a", "aac", "-ar", str(AUDIO_RATE),
        "-movflags", "+faststart", str(out),
    ]
    _run(cmd)
    return out


def make_text_card(
    text: str,
    duration: float = 2.5,
    out: Path | None = None,
    bg: str = "black",
    fg: str = "white",
    fontsize: int = 72,
) -> Path:
    """Render a full-canvas 'inner screen' of centered text with silent audio."""
    if duration <= 0:
        raise MediaError("card duration must be positive")
    out = out or _derived_path()
    wrapped = textwrap.fill(text.strip() or " ", width=22)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(wrapped)
        textfile = tf.name
    drawtext = (
        f"drawtext=fontfile={_font()}:textfile={textfile}:"
        f"fontcolor={fg}:fontsize={fontsize}:line_spacing=16:"
        "x=(w-text_w)/2:y=(h-text_h)/2"
    )
    try:
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c={bg}:s={CANVAS_W}x{CANVAS_H}:r={CANVAS_FPS}:d={duration}",
            "-f", "lavfi", "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
            "-vf", drawtext, "-t", str(duration), "-shortest",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out),
        ])
    finally:
        Path(textfile).unlink(missing_ok=True)
    return out


def overlay_text(
    src: Path,
    text: str,
    position: str = "bottom",
    fontsize: int = 48,
    start: float | None = None,
    end: float | None = None,
    fg: str = "white",
) -> Path:
    """Burn a caption onto a clip, preserving its own dimensions.

    position is 'top' | 'center' | 'bottom'. When start/end are given the
    caption only shows during that window; otherwise it shows for the whole clip.
    """
    out = _derived_path()
    y = {
        "top": "80",
        "center": "(h-text_h)/2",
        "bottom": "h-text_h-100",
    }.get(position, "h-text_h-100")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(textwrap.fill(text.strip() or " ", width=28))
        textfile = tf.name

    drawtext = (
        f"drawtext=fontfile={_font()}:textfile={textfile}:"
        f"fontcolor={fg}:fontsize={fontsize}:line_spacing=8:"
        "box=1:boxcolor=black@0.5:boxborderw=16:"
        f"x=(w-text_w)/2:y={y}"
    )
    if start is not None and end is not None:
        # Single-quote the expression so its commas aren't read as filter separators.
        drawtext += f":enable='between(t,{start},{end})'"

    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", drawtext, "-c:v", "libx264"]
    cmd += ["-c:a", "copy"] if _has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", str(out)]
    try:
        _run(cmd)
    finally:
        Path(textfile).unlink(missing_ok=True)
    return out


def render_timeline(items: list[dict]) -> Path:
    """Assemble an ordered list of timeline items into one clip.

    Each item is one of:
      {"kind": "segment", "path": Path, "start": float, "end": float}
      {"kind": "card",    "text": str, "duration": float, "bg"?: str}
    Items are conformed to the shared canvas, then concatenated.
    """
    if not items:
        raise MediaError("timeline has no items")
    with tempfile.TemporaryDirectory() as td:
        parts: list[Path] = []
        for i, item in enumerate(items):
            part = Path(td) / f"{i:03d}.mp4"
            kind = item.get("kind")
            if kind == "segment":
                normalize_segment(
                    Path(item["path"]), float(item["start"]),
                    float(item["end"]), part,
                )
            elif kind == "card":
                make_text_card(
                    item["text"], float(item.get("duration", 2.5)),
                    out=part, bg=item.get("bg", "black"),
                )
            else:
                raise MediaError(f"unknown timeline item kind: {kind!r}")
            parts.append(part)

        if len(parts) == 1:
            final = _derived_path()
            _run([
                "ffmpeg", "-y", "-i", str(parts[0]),
                "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
                str(final),
            ])
            return final
        return concat(parts)
