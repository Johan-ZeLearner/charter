"""Stage 3: beat / downbeat / tempo tracking (docs/06).

Baseline = numpy/scipy onset-envelope tempo estimate + DP beat tracker. Optional
SOTA adapter = Beat This! (CPJKU 2024, MIT, no madmom dep) used if installed.

The numpy floor now uses a hybrid DFT×ACF tempogram (octave-robust, no 120-BPM
genre prior) plus a drift-aware DP that follows accelerando/ritardando in one pass.
Downbeats: Beat This! emits real downbeats; the floor assumes 4/4 and picks the
bar phase carrying the most onset energy (odd-meter detection is out of floor scope).
"""

from __future__ import annotations

import functools
import importlib.util
import os

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
        # Per-frame tempo curve (octave-locked to the global estimate) → drift-aware DP.
        curve = dsp.estimate_tempo_curve(env, fps, center_bpm=bpm)
        beat_frames = dsp.dp_beat_track(env, fps, curve)
        # Sub-frame refinement removes frame-quantization jitter from the tempo map.
        beat_times = dsp.refine_beat_frames(env, beat_frames) / fps if len(beat_frames) else np.array([])

        # Downbeats are sliced from the *refined* beats by phase, so they stay a true
        # subset of beat_times (deriving them from raw frames would not line up).
        ph = self._downbeat_phase(env, beat_frames)
        downbeats = beat_times[ph::self.beats_per_bar] if len(beat_times) else np.array([])
        return BeatGrid(
            beat_times=beat_times,
            downbeat_times=downbeats,
            bpm=bpm,
            beats_per_bar=self.beats_per_bar,
        )

    def _downbeat_phase(self, env: np.ndarray, beat_frames: np.ndarray) -> int:
        if len(beat_frames) == 0:
            return 0
        strengths = env[np.clip(beat_frames, 0, len(env) - 1)]
        bpb = self.beats_per_bar
        best_phase, best_energy = 0, -np.inf
        for phase in range(bpb):
            energy = strengths[phase::bpb].sum()
            if energy > best_energy:
                best_energy, best_phase = energy, phase
        return best_phase


def best_device() -> str:
    """Pick a torch device for Beat This!.

    NOTE: on this M1 the smoke test measured **CPU faster than MPS** for Beat This!
    (~1.2 s vs ~10.7 s on a 40 s clip): the model is small, so MPS graph-compile +
    the ``PYTORCH_ENABLE_MPS_FALLBACK`` op round-trips cost more than they save. So we
    default to CPU and only use CUDA when present; pass ``device='mps'`` to override.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class BeatThisTracker(BeatTracker):
    """Beat This! (2024 SOTA, no madmom dep) — optional, used if installed.

    Fixed from the original broken adapter: it called ``File2Beats`` (path-only) with
    a sample array. Beat This!'s ``Audio2Beats`` accepts a 1-D float array + sr directly
    and only resamples when ``sr != 22050`` — and our analysis SR *is* 22050, so the
    mono buffer is handed through untouched. The model is loaded once and cached.
    """

    name = "beat-this"

    def __init__(self, checkpoint: str = "final0", device: str | None = None):
        self.checkpoint = checkpoint
        self.device = device or best_device()
        self._a2b = None  # lazily constructed (first call downloads the checkpoint)

    def _model(self):
        if self._a2b is None:
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            from beat_this.inference import Audio2Beats

            self._a2b = Audio2Beats(checkpoint_path=self.checkpoint, device=self.device, dbn=False)
        return self._a2b

    def track(self, audio: AudioBuffer) -> BeatGrid:
        x = np.ascontiguousarray(audio.samples, dtype=np.float32)
        beats, downbeats = self._model()(x, audio.sr)
        beats = np.asarray(beats, dtype=float)
        downbeats = np.asarray(downbeats, dtype=float)
        bpm = 60.0 / np.median(np.diff(beats)) if len(beats) > 1 else 120.0
        return BeatGrid(
            beat_times=beats,
            downbeat_times=downbeats,
            bpm=float(bpm),
            beats_per_bar=4,
        )


def beat_this_available() -> bool:
    return importlib.util.find_spec("beat_this") is not None


@functools.lru_cache(maxsize=4)
def _beat_this_singleton(checkpoint: str = "final0", device: str | None = None) -> BeatThisTracker:
    """One Beat This! instance per (checkpoint, device) so its ~77 MB weights load ONCE.

    The studio re-tracks per section (a new analyze_window per tap / re-track / lock-off),
    so constructing a fresh tracker each call would reload the model from disk every time.
    Caching here makes the per-instance lazy ``_a2b`` cache actually persist across calls.
    """
    return BeatThisTracker(checkpoint=checkpoint, device=device)


def choose_beat_tracker(prefer: str = "auto") -> BeatTracker:
    """Select a beat tracker. ``auto``/``beat-this`` → Beat This! if installed, else numpy.

    The Beat This! instance is memoised (weights load once); NumpyBeatTracker is cheap
    and stateless so it stays per-call.
    """
    if prefer in ("auto", "beat-this") and beat_this_available():
        return _beat_this_singleton()
    return NumpyBeatTracker()
