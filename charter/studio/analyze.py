"""Song analysis for the beat-grid studio: beats, drift-tracking tempo, sections.

The grid is the foundation everything else (drums, bass, other lines) will be
built on, so this stage is the one to ground. It returns a *per-beat* grid (not a
single BPM) so tempo drift is preserved, a tempo curve so drift is visible, the
song sections, and a downsampled waveform for the DAW timeline.

All adjustable: ``tempo_mult`` (½/×2 octave fix), ``tempo_hint`` (bias the
detector toward a known BPM), ``beats_per_bar`` and ``phase`` (which beat is "1").
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..audio import dsp
from ..audio.ingest import decode_audio
from ..audio.interfaces import BeatGrid
from ..audio.quantize import resample_grid
from .sections import detect_sections

ANALYSIS_SR = 22050        # plenty for beats/sections; half the cost of 44.1k
WAVEFORM_BUCKETS = 2000    # downsampled peaks for the timeline


def _waveform_peaks(samples: np.ndarray, buckets: int = WAVEFORM_BUCKETS) -> list[float]:
    n = len(samples)
    if n == 0:
        return []
    step = max(1, n // buckets)
    usable = (n // step) * step
    chunks = np.abs(samples[:usable]).reshape(-1, step)
    peaks = chunks.max(axis=1)
    m = peaks.max()
    if m > 0:
        peaks = peaks / m
    return [round(float(p), 3) for p in peaks]


def _downbeat_phase(env: np.ndarray, fps: float, beat_times: np.ndarray, bpb: int) -> int:
    """Bar phase (0..bpb-1) whose beats carry the most onset energy."""
    if len(beat_times) == 0:
        return 0
    frames = np.clip((beat_times * fps).astype(int), 0, len(env) - 1)
    strengths = env[frames]
    best_phase, best = 0, -np.inf
    for p in range(bpb):
        e = strengths[p::bpb].sum()
        if e > best:
            best, best_phase = e, p
    return best_phase


def analyze_song(
    path: str | Path,
    *,
    max_seconds: float | None = None,
    tempo_mult: float = 1.0,
    tempo_hint: float | None = None,
    beats_per_bar: int = 4,
    phase: int | None = None,
) -> dict:
    """Analyze the song and return a JSON-friendly grid + structure payload."""
    audio = decode_audio(path, sr=ANALYSIS_SR, max_seconds=max_seconds, loudnorm=False)
    x, sr = audio.samples, audio.sr
    duration = len(x) / sr

    env, fps = dsp.onset_envelope(x, sr)
    bpm0 = dsp.estimate_tempo(env, fps, prior_bpm=tempo_hint or 120.0)
    beat_frames = dsp.dp_beat_track(env, fps, bpm0)
    beat_times = dsp.refine_beat_frames(env, beat_frames) / fps if len(beat_frames) else np.array([])

    bpb = max(2, int(beats_per_bar))
    ph = phase if phase is not None else _downbeat_phase(env, fps, beat_times, bpb)
    ph = ph % bpb
    downbeats = beat_times[ph::bpb] if len(beat_times) else np.array([])

    grid = BeatGrid(beat_times=beat_times, downbeat_times=downbeats, bpm=bpm0, beats_per_bar=bpb)
    grid = resample_grid(grid, float(tempo_mult))
    beats = np.asarray(grid.beat_times, dtype=float)
    # recompute downbeats after a tempo multiply (beat count changed)
    downbeats = beats[ph % bpb :: bpb] if len(beats) else np.array([])

    # per-beat tempo curve (drift made visible), smoothed lightly
    if len(beats) >= 2:
        local = 60.0 / np.clip(np.diff(beats), 1e-3, None)
        local = np.clip(local, 30.0, 400.0)
        tempo_curve = [
            {"t": round(float(beats[i + 1]), 3), "bpm": round(float(local[i]), 1)}
            for i in range(len(local))
        ]
        med_bpm = round(float(np.median(local)), 1)
    else:
        tempo_curve, med_bpm = [], round(bpm0, 1)

    sections = detect_sections(x, sr, downbeats)

    return {
        "duration": round(duration, 3),
        "bpm": med_bpm,
        "beatsPerBar": bpb,
        "phase": ph % bpb,
        "tempoMult": float(tempo_mult),
        "beats": [round(float(b), 4) for b in beats],
        "downbeats": [round(float(b), 4) for b in downbeats],
        "tempoCurve": tempo_curve,
        "sections": sections,
        "waveform": _waveform_peaks(x),
        "analysis": {
            "rawBpm": round(float(bpm0), 1),
            "beats": int(len(beats)),
            "downbeats": int(len(downbeats)),
            "sections": len(sections),
        },
    }
