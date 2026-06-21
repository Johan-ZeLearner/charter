"""Small shared helpers for the studio server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audio.ingest import read_tags


def song_meta(path: str | Path) -> dict[str, Any]:
    """Title/artist/duration for the loaded song (best-effort via ffprobe)."""
    tags = read_tags(path)
    return {
        "name": tags.title or Path(path).stem,
        "artist": tags.artist or "Unknown Artist",
        "duration_s": (tags.duration_ms or 0) / 1000.0,
    }
