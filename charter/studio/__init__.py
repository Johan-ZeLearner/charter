"""charter studio — a tune-and-preview loop for the audio frontend.

The auto-charter's baseline ADT is a pile of thresholds; thresholds are only
useful if the feedback loop is seconds, not a full-song render. The studio runs
the pipeline on a short window (10-20 s, anywhere in the tune), returns the
notes with their times, and a Clone-Hero-style highway renders them in sync with
the clip audio so the result can be judged by eye and ear — then the settings
get dialed in per song (docs/01 "AI draft + cleanup", docs/09 review surface).

This package is the previewer; the OCTAVE-style React/R3F editor is the next
iteration. The Three.js highway scene ports almost 1:1 into React-Three-Fiber.
"""

from __future__ import annotations

from .presets import DEFAULTS, PRESETS, build_engine, resolve_settings
from .service import run_preview, song_meta

__all__ = [
    "DEFAULTS",
    "PRESETS",
    "build_engine",
    "resolve_settings",
    "run_preview",
    "song_meta",
]
