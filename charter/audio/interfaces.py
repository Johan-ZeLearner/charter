"""Shared types + swappable stage interfaces for the audio frontend.

Each stage (separation, beat tracking, transcription) is a small interface with
a light always-available baseline and an optional SOTA adapter, per the docs/08
service boundaries ("separation swappable from day one", etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class AudioBuffer:
    """Mono analysis signal."""

    samples: np.ndarray  # float32, mono, in [-1, 1]
    sr: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sr

    def rms(self) -> float:
        if self.samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(self.samples.astype(np.float64) ** 2)))


@dataclass
class BeatGrid:
    """Tracked beats. ``beat_times`` are quarter-note positions in seconds."""

    beat_times: np.ndarray
    downbeat_times: np.ndarray
    bpm: float  # global estimate, for reporting
    beats_per_bar: int = 4


@dataclass
class DrumOnset:
    """A transcribed drum hit (pre-quantization), in seconds."""

    time_s: float
    gm_note: int
    velocity: int
    confidence: float = 1.0


@dataclass
class Diagnostics:
    """Honest signals surfaced to the user / future REVIEW.md (docs/09)."""

    drum_rms: float = 0.0
    bpm: float = 0.0
    beats: int = 0
    onsets: int = 0
    notes: int = 0
    separator: str = ""
    beat_tracker: str = ""
    transcriber: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def gate(self) -> str:
        """GO / CAUTION / REFUSE on drum prominence (docs/09; STRUM used RMS>=0.018)."""
        if self.drum_rms < 0.012:
            return "REFUSE"
        if self.drum_rms < 0.018:
            return "CAUTION"
        return "GO"


class Separator:
    name = "base"

    def separate(self, audio: AudioBuffer) -> AudioBuffer:  # pragma: no cover
        raise NotImplementedError


class BeatTracker:
    name = "base"

    def track(self, audio: AudioBuffer) -> BeatGrid:  # pragma: no cover
        raise NotImplementedError


class DrumTranscriber:
    name = "base"

    def transcribe(self, audio: AudioBuffer) -> list[DrumOnset]:  # pragma: no cover
        raise NotImplementedError
