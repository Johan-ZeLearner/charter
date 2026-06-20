"""Stage 5: tempo-map building + onset quantization to the 16th grid."""

from __future__ import annotations

import numpy as np

from charter.audio.interfaces import BeatGrid, DrumOnset
from charter.audio.quantize import build_tempo_map, quantize_onsets


def _grid_120(beats=5):
    times = np.arange(beats) * 0.5  # 120 BPM
    return BeatGrid(beat_times=times, downbeat_times=times[::4], bpm=120.0, beats_per_bar=4)


def test_quantize_snaps_to_sixteenth_grid():
    grid = _grid_120()
    onsets = [
        DrumOnset(0.0, 36, 100),  # beat 0 -> tick 0
        DrumOnset(0.25, 38, 100),  # 8th between beats 0 and 1 -> tick 96
        DrumOnset(0.5, 42, 100),  # beat 1 -> tick 192
        DrumOnset(0.30, 42, 100),  # near the 8th -> snaps to 96
    ]
    events = quantize_onsets(onsets, grid, subdivisions=4)
    ticks = sorted(e.tick for e in events)
    assert ticks == [0, 96, 96, 192]


def test_tempo_map_constant_is_single_marker():
    tm = build_tempo_map(_grid_120())
    assert len(tm.tempos) == 1
    assert abs(tm.tempos[0].bpm - 120.0) < 0.5
    assert tm.time_sigs[0].numerator == 4


def test_tempo_map_tracks_changes():
    # beats that accelerate: intervals 0.5, 0.5, 0.4, 0.4 -> 120, 120, 150, 150
    times = np.array([0.0, 0.5, 1.0, 1.4, 1.8])
    grid = BeatGrid(beat_times=times, downbeat_times=times[::4], bpm=120.0)
    tm = build_tempo_map(grid)
    bpms = [round(e.bpm) for e in tm.tempos]
    assert 120 in bpms and 150 in bpms
    assert len(tm.tempos) == 2  # coalesced into two segments
