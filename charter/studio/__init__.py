"""charter studio — a beat-grid & song-structure editor.

Restarted from a simpler base: the goal is to ground the FOUNDATION — an
accurate, drift-tracking beat grid plus song sections — before anything is built
on it. Everything downstream (drums, bass, other instrument lines) snaps to this
grid, so it must be inspectable and correctable first.

Two views: a Clone-Hero-style highway (judge the beat by eye + metronome click)
and a DAW-style timeline (waveform + beats/bars + sections + tempo curve).

The previous auto-charter studio (ADT engines, pattern mode) lives on the
``studio-autocharter-v1`` branch for reference.
"""

from __future__ import annotations

from .analyze import analyze_song
from .service import song_meta

__all__ = ["analyze_song", "song_meta"]
