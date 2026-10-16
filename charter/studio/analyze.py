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
from ..audio.beats import BeatThisTracker, choose_beat_tracker
from ..audio.ingest import decode_audio
from ..audio.interfaces import AudioBuffer, BeatGrid
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


def _tempo_curve(beats: np.ndarray) -> tuple[list[dict], float | None]:
    """Per-beat tempo curve (drift made visible) + median BPM.

    Each point is anchored at the *later* beat of the pair, so the curve reads as
    "the tempo arriving at this beat" — the same convention used everywhere the
    grid is drawn. Returns (curve, median_bpm) with median_bpm None for <2 beats.
    """
    beats = np.asarray(beats, dtype=float)
    if len(beats) < 2:
        return [], None
    local = 60.0 / np.clip(np.diff(beats), 1e-3, None)
    local = np.clip(local, 30.0, 400.0)
    curve = [
        {"t": round(float(beats[i + 1]), 3), "bpm": round(float(local[i]), 1)}
        for i in range(len(local))
    ]
    return curve, round(float(np.median(local)), 1)


def _phase_from_downbeats(beats: np.ndarray, downbeats: np.ndarray, bpb: int) -> int:
    """Most-common bar phase of the beats nearest to a tracker's real downbeats."""
    beats = np.asarray(beats, dtype=float)
    downbeats = np.asarray(downbeats, dtype=float)
    if len(beats) < 2 or len(downbeats) == 0:
        return 0
    pos = np.clip(np.searchsorted(beats, downbeats), 1, len(beats) - 1)
    left = pos - 1
    nearest = np.where(np.abs(beats[pos] - downbeats) < np.abs(beats[left] - downbeats), pos, left)
    return int(np.bincount((nearest % bpb).astype(int), minlength=bpb).argmax())


def _detect_beats(x: np.ndarray, sr: int, *, engine: str = "auto",
                  tempo_hint: float | None = None, anchor_local: float | None = None):
    """Detect beats on a local buffer. Returns (beat_times, downbeats|None, bpm0, env, fps, used).

    ``used`` is the engine that actually ran ("beat-this" / "numpy" / "numpy-hint"), reported
    independently of ``downbeats`` so the label is right even if Beat This! emits none.

    Routing (the key wiring): a **tap** (``tempo_hint``) means the user is overriding the
    rate, so we take the controllable numpy path — the tapped BPM seeds a tight drift
    band and ``anchor_local`` becomes a HARD pin in the DP (the fix for "a correct tap
    can't win"). With no tap we use the selected tracker: **Beat This!** when available
    (SOTA, no 120 prior, real downbeats), else the numpy floor (hybrid tempogram +
    drift-aware DP). ``anchor_local`` still hard-pins the numpy floor.
    """
    env, fps = dsp.onset_envelope(x, sr)
    hint = tempo_hint if (tempo_hint and tempo_hint > 0) else None
    anchors = [int(round(anchor_local * fps))] if anchor_local is not None else None

    if hint is None:
        tracker = choose_beat_tracker(engine)
        if isinstance(tracker, BeatThisTracker):
            try:
                grid = tracker.track(AudioBuffer(samples=np.ascontiguousarray(x, np.float32), sr=sr))
                return (np.asarray(grid.beat_times, float), np.asarray(grid.downbeat_times, float),
                        float(grid.bpm), env, fps, "beat-this")
            except Exception:
                pass  # fall through to the always-available numpy floor
        bpm0 = dsp.estimate_tempo(env, fps)
        curve = dsp.estimate_tempo_curve(env, fps, center_bpm=bpm0)
        used = "numpy"
    else:
        bpm0 = float(hint)
        # tight drift band so the tapped rate is held, but the DP still snaps to real onsets
        curve = dsp.estimate_tempo_curve(env, fps, center_bpm=bpm0, drift=0.08)
        used = "numpy-hint"

    frames = dsp.dp_beat_track(env, fps, curve, anchors=anchors)
    beats = dsp.refine_beat_frames(env, frames) / fps if len(frames) else np.array([])
    return beats, None, bpm0, env, fps, used


def analyze_song(
    path: str | Path,
    *,
    max_seconds: float | None = None,
    tempo_mult: float = 1.0,
    tempo_hint: float | None = None,
    beats_per_bar: int = 4,
    phase: int | None = None,
    engine: str = "auto",
) -> dict:
    """Analyze the song and return a JSON-friendly grid + structure payload."""
    audio = decode_audio(path, sr=ANALYSIS_SR, max_seconds=max_seconds, loudnorm=False)
    x, sr = audio.samples, audio.sr
    duration = len(x) / sr

    beat_times, bt_downbeats, bpm0, env, fps, used = _detect_beats(
        x, sr, engine=engine, tempo_hint=tempo_hint)

    bpb = max(2, int(beats_per_bar))
    if phase is not None:
        ph = phase % bpb
    elif bt_downbeats is not None:
        ph = _phase_from_downbeats(beat_times, bt_downbeats, bpb)
    else:
        ph = _downbeat_phase(env, fps, beat_times, bpb) % bpb
    downbeats = beat_times[ph::bpb] if len(beat_times) else np.array([])

    grid = BeatGrid(beat_times=beat_times, downbeat_times=downbeats, bpm=bpm0, beats_per_bar=bpb)
    grid = resample_grid(grid, float(tempo_mult))
    beats = np.asarray(grid.beat_times, dtype=float)
    # recompute downbeats after a tempo multiply (beat count changed)
    downbeats = beats[ph % bpb :: bpb] if len(beats) else np.array([])

    # per-beat tempo curve (drift made visible)
    tempo_curve, med_bpm = _tempo_curve(beats)
    if med_bpm is None:
        med_bpm = round(bpm0, 1)

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
        "tracker": used,
        "analysis": {
            "rawBpm": round(float(bpm0), 1),
            "beats": int(len(beats)),
            "downbeats": int(len(downbeats)),
            "sections": len(sections),
            "tracker": used,
        },
    }


def _locked_grid(start: float, end: float, bpm: float, anchor: float | None,
                 bpb: int, tempo_mult: float) -> dict:
    """A metronomic grid built straight from a tapped tempo — detection bypassed.

    Beats sit at exactly ``60/bpm`` apart, placed so one lands on ``anchor`` (the
    marked beat 1, defaulting to ``start``). The anchor is bar phase 0, so every
    ``bpb``-th beat from it is a downbeat. This is the manual-authority escape hatch:
    when the detector fights the user's ear, the user's tap is taken as ground truth.
    """
    bpm = max(1.0, float(bpm))
    period = 60.0 / bpm
    anchor_t = float(anchor) if anchor is not None else start
    # integer beat offsets from the anchor that fall in the half-open window [start, end)
    k0 = int(np.ceil((start - anchor_t) / period - 1e-9))
    k1 = int(np.floor((end - anchor_t) / period + 1e-9))
    ks = np.arange(k0, k1 + 1)
    beats = anchor_t + ks * period
    keep = (beats >= start - 1e-6) & (beats < end)
    beats, ks = beats[keep], ks[keep]
    downbeats = beats[(ks % bpb) == 0]  # anchor (k=0) is beat 1
    tempo_curve, _ = _tempo_curve(beats)
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "beats": [round(float(b), 4) for b in beats],
        "downbeats": [round(float(b), 4) for b in downbeats],
        "bpm": round(bpm, 1),
        "beatsPerBar": bpb,
        "phase": 0,
        "tempoMult": float(tempo_mult),
        "tempoCurve": tempo_curve,
        "locked": True,
        "tracker": "locked",
        "analysis": {
            "rawBpm": round(bpm, 1),
            "beats": int(len(beats)),
            "downbeats": int(len(downbeats)),
            "tracker": "locked",
        },
    }


def analyze_window(
    path: str | Path,
    start: float,
    end: float,
    *,
    pad: float = 3.0,
    tempo_mult: float = 1.0,
    tempo_hint: float | None = None,
    beats_per_bar: int = 4,
    phase: int | None = None,
    anchor: float | None = None,
    lock: bool = False,
    engine: str = "auto",
) -> dict:
    """Re-track the beat grid for a single region ``[start, end)`` in isolation.

    The global pass picks one tempo prior for the whole song, so it mis-tracks
    sections that sit at a different tempo/feel (the usual half-time octave error).
    This re-runs detection on just the region with the region's own controls and
    returns beats in **absolute song time**, so the studio can splice the result
    back into the global grid without disturbing the rest of the song.

    Two ways to drive it:

    * **Detect (seeded)** — the default. ``tempo_hint`` (a tapped/known BPM) biases
      the tracker's period prior, ``anchor`` (a time marked "beat 1") sets the bar
      phase, ``phase`` is the explicit fallback. The detector still follows onsets,
      so a strong onset pattern can pull it off your tap.
    * **Lock (manual authority)** — ``lock=True`` with a positive ``tempo_hint``.
      The grid is *built* metronomically at ``tempo_hint * tempo_mult`` BPM, anchored
      so a beat sits exactly on ``anchor`` (or ``start``). Detection is bypassed
      entirely — for sections where the detector disagrees with your ear, your tap
      IS the grid. Pair with split/merge to lock each tempo region on its own.

    A ``pad`` of context on each side is decoded (detect mode) so the onset envelope
    and DP tracker have run-up/run-out; padding beats are dropped before returning.
    """
    start = max(0.0, float(start))
    end = float(end)
    bpb = max(2, int(beats_per_bar))
    empty = {
        "start": round(start, 3), "end": round(max(start, end), 3),
        "beats": [], "downbeats": [], "bpm": None, "beatsPerBar": bpb,
        "phase": 0, "tempoMult": float(tempo_mult), "tempoCurve": [], "locked": False,
        "tracker": "none",
        "analysis": {"rawBpm": None, "beats": 0, "downbeats": 0, "tracker": "none"},
    }
    if end <= start:
        return empty

    hint = float(tempo_hint) if (tempo_hint and tempo_hint > 0) else None
    if lock and hint is not None:
        return _locked_grid(start, end, hint * float(tempo_mult), anchor, bpb, float(tempo_mult))

    a = max(0.0, start - pad)
    audio = decode_audio(
        path, sr=ANALYSIS_SR, start_seconds=a or None,
        max_seconds=(end - a) + pad, loudnorm=False,
    )
    x, sr = audio.samples, audio.sr
    if len(x) == 0:
        return empty

    anchor_local = (float(anchor) - a) if anchor is not None else None
    beat_local, bt_downbeats, bpm0, env, fps, used = _detect_beats(
        x, sr, engine=engine, tempo_hint=tempo_hint, anchor_local=anchor_local)

    # apply the tempo multiplier on the padded grid, then shift to song time
    grid = BeatGrid(beat_times=beat_local, downbeat_times=np.array([]), bpm=bpm0, beats_per_bar=bpb)
    grid = resample_grid(grid, float(tempo_mult))
    beat_abs = np.asarray(grid.beat_times, dtype=float) + a

    # drop the padding — keep only beats inside the half-open region [start, end).
    # The tiny lower fudge absorbs offset rounding; the upper bound is strict so a beat
    # on the section boundary (the next section's downbeat) is never double-counted.
    # This MUST match the frontend's composeGrid `covered()` test so the splice is clean.
    mask = (beat_abs >= start - 1e-6) & (beat_abs < end)
    beats = beat_abs[mask]

    if len(beats):
        if anchor is not None:
            ph = int(np.argmin(np.abs(beats - float(anchor)))) % bpb
        elif phase is not None:
            ph = int(phase) % bpb
        elif bt_downbeats is not None and len(bt_downbeats):
            ph = _phase_from_downbeats(beats, np.asarray(bt_downbeats, float) + a, bpb)
        else:
            ph = _downbeat_phase(env, fps, beats - a, bpb)  # local-frame for env indexing
        downbeats = beats[ph % bpb :: bpb]
    else:
        ph, downbeats = 0, np.array([])

    tempo_curve, med_bpm = _tempo_curve(beats)
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "beats": [round(float(b), 4) for b in beats],
        "downbeats": [round(float(b), 4) for b in downbeats],
        "bpm": med_bpm if med_bpm is not None else round(bpm0, 1),
        "beatsPerBar": bpb,
        "phase": ph % bpb,
        "tempoMult": float(tempo_mult),
        "tempoCurve": tempo_curve,
        "locked": False,
        "tracker": used,
        "analysis": {
            "rawBpm": round(float(bpm0), 1),
            "beats": int(len(beats)),
            "downbeats": int(len(downbeats)),
            "tracker": used,
        },
    }
