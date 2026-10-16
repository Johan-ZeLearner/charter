"""BeatTracker interface: numpy floor always, Beat This! adapter when installed.

Guards the contract analyze.py relies on (sorted beats in seconds, a positive bpm,
downbeats a subset of beats) and that the previously-broken Beat This! adapter now
runs on a sample array (it used to call the path-only File2Beats and never ran).
"""

from __future__ import annotations

import numpy as np
import pytest

from charter.audio.beats import (
    BeatThisTracker,
    NumpyBeatTracker,
    beat_this_available,
    best_device,
    choose_beat_tracker,
)
from charter.audio.interfaces import AudioBuffer
from tests.fixtures.synth import synth_even_kicks


def _buf(bpm=180.0, count=64):
    t = synth_even_kicks(bpm=bpm, count=count)
    return AudioBuffer(samples=np.ascontiguousarray(t.samples, np.float32), sr=t.sr)


def test_numpy_tracker_grid_contract():
    grid = NumpyBeatTracker().track(_buf(bpm=180.0))
    bt = np.asarray(grid.beat_times)
    assert len(bt) > 4
    assert np.all(np.diff(bt) > 0), "beats must be sorted/strictly increasing"
    assert grid.bpm > 100.0
    db = np.asarray(grid.downbeat_times)
    if len(db):
        bset = set(np.round(bt, 6))
        assert all(round(float(d), 6) in bset for d in db), "downbeats ⊂ beats"


def test_choose_beat_tracker_prefers_numpy_when_asked():
    assert isinstance(choose_beat_tracker("numpy"), NumpyBeatTracker)


def test_best_device_is_a_known_value():
    assert best_device() in ("cpu", "cuda", "mps")


@pytest.mark.skipif(not beat_this_available(), reason="beat_this not installed")
def test_beat_this_adapter_runs_on_array():
    """Regression: the old adapter called File2Beats (path-only) with an array and
    never ran. Audio2Beats accepts the array; at 22050 Hz no resample happens."""
    grid = BeatThisTracker(device="cpu").track(_buf(bpm=180.0, count=80))
    bt = np.asarray(grid.beat_times)
    assert len(bt) > 4
    assert np.all(np.diff(bt) > 0)
    assert grid.bpm > 0
