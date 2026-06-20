"""Stage 3: beat / downbeat / tempo tracking (docs/06).

Baseline = numpy/scipy onset-envelope tempo estimate + DP beat tracker. Optional
SOTA adapter = Beat This! (used if installed). Downbeats: assume 4/4 and pick the
bar phase with the most onset energy (odd-meter detection is out of baseline
scope — flagged for the SOTA path).
"""

from __future__ import annotations

import importlib.util

import numpy as np

from . import dsp
from .interfaces import AudioBuffer, BeatGrid, BeatTracker


class NumpyBeatTracker(BeatTracker):
    name = "numpy-dp"

    def __init__(self, beats_per_bar: int = 4):
        self.beats_per_bar = beats_per_bar

    def track(self, audio: AudioBuffer) -> BeatGrid:
        env, fps = dsp.onset_envelope(audio.samples, audio.sr)
        bpm = dsp.estimate_tempo(env, fps)
        beat_frames = dsp.dp_beat_track(env, fps, bpm)
        # Sub-frame refinement removes frame-quantization jitter from the tempo map.
        beat_times = dsp.refine_beat_frames(env, beat_frames) / fps if len(beat_frames) else np.array([])

        downbeats = self._pick_downbeats(env, beat_frames)
        return BeatGrid(
            beat_times=beat_times,
            downbeat_times=downbeats / fps if len(downbeats) else np.array([]),
            bpm=bpm,
            beats_per_bar=self.beats_per_bar,
        )

    def _pick_downbeats(self, env: np.ndarray, beat_frames: np.ndarray) -> np.ndarray:
        if len(beat_frames) == 0:
            return np.array([], dtype=int)
        strengths = env[np.clip(beat_frames, 0, len(env) - 1)]
        bpb = self.beats_per_bar
        best_phase, best_energy = 0, -np.inf
        for phase in range(bpb):
            energy = strengths[phase::bpb].sum()
            if energy > best_energy:
                best_energy, best_phase = energy, phase
        return beat_frames[best_phase::bpb]


class BeatThisTracker(BeatTracker):  # pragma: no cover
    """Beat This! (2024 SOTA, no madmom dep) — optional, used if installed."""

    name = "beat-this"

    def track(self, audio: AudioBuffer) -> BeatGrid:
        from beat_this.inference import File2Beats

        f2b = File2Beats()
        beats, downbeats = f2b(audio.samples, audio.sr)
        beats = np.asarray(beats)
        bpm = 60.0 / np.median(np.diff(beats)) if len(beats) > 1 else 120.0
        return BeatGrid(
            beat_times=beats,
            downbeat_times=np.asarray(downbeats),
            bpm=float(bpm),
            beats_per_bar=4,
        )


def beat_this_available() -> bool:
    return importlib.util.find_spec("beat_this") is not None


def choose_beat_tracker(prefer: str = "auto") -> BeatTracker:
    if prefer in ("auto", "beat-this") and beat_this_available():
        return BeatThisTracker()
    return NumpyBeatTracker()
