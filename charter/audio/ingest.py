"""Stage 0: ingest — decode, loudness-normalize, tag, and (re)encode audio.

Uses the system FFmpeg/ffprobe binaries (no python audio deps). Decodes to a
mono float32 numpy buffer for analysis and encodes the playable ``song.opus``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .interfaces import AudioBuffer

ANALYSIS_SR = 44100


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@dataclass
class Tags:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: str | None = None
    duration_ms: int = 0


def decode_audio(path: str | Path, *, sr: int = ANALYSIS_SR,
                 loudnorm: bool = True) -> AudioBuffer:
    """Decode any FFmpeg-readable file to a mono float32 buffer at ``sr``."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg/ffprobe not found on PATH")
    af = "loudnorm=I=-16:TP=-1.5:LRA=11" if loudnorm else "anull"
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-ac", "1", "-ar", str(sr), "-af", af, "-f", "f32le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {proc.stderr.decode(errors='replace')[:400]}")
    samples = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)
    return AudioBuffer(samples=samples, sr=sr)


def read_tags(path: str | Path) -> Tags:
    """Read metadata via ffprobe (best-effort)."""
    if not ffmpeg_available():
        return Tags()
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return Tags()
    fmt = json.loads(proc.stdout).get("format", {})
    t = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    duration_ms = int(float(fmt.get("duration", 0.0)) * 1000)
    year = t.get("date") or t.get("year")
    if year and len(year) >= 4:
        year = year[:4]
    return Tags(
        title=t.get("title"),
        artist=t.get("artist"),
        album=t.get("album"),
        year=year,
        duration_ms=duration_ms,
    )


def encode_opus(src: str | Path, dst: str | Path, *, bitrate: str = "80k") -> Path:
    """Encode ``src`` to ``dst`` as Opus (~80 kbps, the recommended CH codec)."""
    dst = Path(dst)
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(src),
        "-c:a", "libopus", "-b:a", bitrate, str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"opus encode failed: {proc.stderr.decode(errors='replace')[:400]}")
    return dst
