"""Stage 5: tempo map + tempo-aware quantization (docs/06).

Each tracked beat is one quarter note → chart tick ``i * 192``. The per-beat
tempo map is derived from the ACTUAL inter-beat intervals (never a single global
BPM), and onsets snap to a subdivided beat grid (16ths by default) at ~100%
strength so every note lands on a hittable grid line.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import medfilt

from ..drumnote.tempo import DEFAULT_RESOLUTION, TempoEvent, TempoMap, TimeSigEvent
from ..mapping.stage6 import RawDrumEvent
from .interfaces import BeatGrid, DrumOnset


def build_tempo_map(grid: BeatGrid, *, resolution: int = DEFAULT_RESOLUTION,
                    coalesce_bpm: float = 1.0, smooth: int = 5) -> TempoMap:
    """Per-beat tempo map from inter-beat intervals.

    Beat times carry frame-quantization jitter (~±1-2 BPM), which would otherwise
    produce a marker per beat. We median-smooth the per-beat BPM series first,
    then emit a marker only when the smoothed tempo moves by more than
    ``coalesce_bpm`` — so a constant song collapses to ~1 marker while genuine
    drift is still tracked (docs/06: build the map from beats, don't assume one BPM).
    """
    beats = np.asarray(grid.beat_times, dtype=float)
    tempos: list[TempoEvent] = []
    if len(beats) >= 2:
        intervals = np.diff(beats)
        intervals[intervals <= 0] = np.nan
        bpms = np.clip(60.0 / intervals, 30.0, 400.0)
        bpms = np.nan_to_num(bpms, nan=float(grid.bpm or 120.0))
        if smooth > 1 and len(bpms) >= smooth:
            k = smooth if smooth % 2 == 1 else smooth + 1
            k = min(k, len(bpms) if len(bpms) % 2 == 1 else len(bpms) - 1)
            if k >= 3:
                bpms = medfilt(bpms, kernel_size=k)
        last_bpm = None
        for i, bpm in enumerate(bpms):
            if last_bpm is None or abs(bpm - last_bpm) > coalesce_bpm:
                tempos.append(TempoEvent(i * resolution, float(bpm)))
                last_bpm = float(bpm)
    if not tempos:
        tempos.append(TempoEvent(0, grid.bpm or 120.0))
    time_sigs = [TimeSigEvent(0, grid.beats_per_bar, 2)]  # x/4
    return TempoMap(resolution=resolution, tempos=tempos, time_sigs=time_sigs).normalized()


def _beats_position(t: float, beats: np.ndarray) -> float:
    """Continuous position of time ``t`` measured in beats (fractional)."""
    n = len(beats)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.0
    if t <= beats[0]:
        interval = beats[1] - beats[0]
        return (t - beats[0]) / interval if interval > 0 else 0.0
    if t >= beats[-1]:
        interval = beats[-1] - beats[-2]
        return (n - 1) + ((t - beats[-1]) / interval if interval > 0 else 0.0)
    b = int(np.searchsorted(beats, t, side="right") - 1)
    interval = beats[b + 1] - beats[b]
    frac = (t - beats[b]) / interval if interval > 0 else 0.0
    return b + frac


def quantize_onsets(onsets: list[DrumOnset], grid: BeatGrid, *,
                    subdivisions: int = 4,
                    resolution: int = DEFAULT_RESOLUTION) -> list[RawDrumEvent]:
    """Snap onsets to a subdivided beat grid and return tick-based events."""
    beats = np.asarray(grid.beat_times, dtype=float)
    step = resolution // subdivisions
    events: list[RawDrumEvent] = []
    for o in onsets:
        pos_beats = _beats_position(o.time_s, beats)
        snapped_sub = round(pos_beats * subdivisions)
        tick = max(0, snapped_sub * step)
        events.append(RawDrumEvent(tick=tick, gm_note=o.gm_note, velocity=o.velocity))
    events.sort(key=lambda e: (e.tick, e.gm_note))
    return events
