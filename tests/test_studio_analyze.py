"""Studio per-section re-tracking (analyze_window): the beat-grid rework loop.

The studio lets the user rework one section's beat grid in isolation and splice it
back into the global grid. These tests pin the contract analyze_window must hold
for that splice to be safe: region beats are in ABSOLUTE song time, strictly
inside the requested window, sorted, and the tempo seeds (hint/anchor) actually
steer the result.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from charter.audio.ingest import ffmpeg_available
from charter.studio.analyze import analyze_window
from tests.fixtures.synth import synth_drum_track

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


@pytest.fixture
def song_wav(tmp_path):
    """A clean 120 BPM synthetic drum track on disk (decodable by ffmpeg)."""
    t = synth_drum_track(bpm=120.0, bars=16)
    wav = tmp_path / "song.wav"
    wavfile.write(wav, t.sr, (t.samples * 32767).astype(np.int16))
    return wav, t


@needs_ffmpeg
def test_region_beats_are_absolute_in_bounds_and_sorted(song_wav):
    wav, _ = song_wav
    start, end = 6.0, 14.0
    r = analyze_window(wav, start, end)
    beats = r["beats"]
    assert len(beats) >= 2
    assert beats == sorted(beats), "spliceable grid must be sorted"
    assert all(start - 1e-6 <= b < end for b in beats), "padding must be dropped; beats in song time"
    assert r["start"] == round(start, 3) and r["end"] == round(end, 3)
    # downbeats are a subset of the beats
    bset = {round(b, 4) for b in beats}
    assert all(round(d, 4) in bset for d in r["downbeats"])


@needs_ffmpeg
def test_region_auto_recovers_true_tempo(song_wav):
    wav, t = song_wav
    r = analyze_window(wav, 4.0, 12.0)
    assert r["bpm"] == pytest.approx(t.bpm, abs=8.0)


@needs_ffmpeg
def test_tempo_hint_seeds_the_tracker(song_wav):
    """A tapped/known BPM is used as the period prior — your suggestion wins."""
    wav, _ = song_wav
    auto = analyze_window(wav, 4.0, 12.0)
    doubled = analyze_window(wav, 4.0, 12.0, tempo_hint=auto["bpm"] * 2)
    # twice the prior ⇒ ~twice the beats in the same window
    assert doubled["analysis"]["beats"] > auto["analysis"]["beats"] * 1.5
    assert doubled["bpm"] == pytest.approx(auto["bpm"] * 2, rel=0.18)


@needs_ffmpeg
def test_tempo_mult_doubles_beat_density(song_wav):
    wav, _ = song_wav
    base = analyze_window(wav, 4.0, 12.0)
    twox = analyze_window(wav, 4.0, 12.0, tempo_mult=2.0)
    assert twox["analysis"]["beats"] > base["analysis"]["beats"] * 1.5
    # multiplied beats stay inside the window (no padding leaks in)
    assert all(4.0 - 1e-6 <= b < 12.0 for b in twox["beats"])


@needs_ffmpeg
def test_anchor_sets_downbeat_phase(song_wav):
    """The beat nearest the anchor becomes a downbeat."""
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0, beats_per_bar=4)
    assert len(r["beats"]) >= 4
    anchor = r["beats"][1]  # ask for beat index 1 to be the downbeat
    r2 = analyze_window(wav, 4.0, 12.0, beats_per_bar=4, anchor=anchor)
    # the anchored beat must land on a downbeat
    dset = {round(d, 4) for d in r2["downbeats"]}
    assert round(anchor, 4) in dset


@needs_ffmpeg
def test_empty_window_is_safe(song_wav):
    wav, _ = song_wav
    r = analyze_window(wav, 10.0, 10.0)  # zero-length
    assert r["beats"] == [] and r["downbeats"] == []
    assert r["bpm"] is None


@needs_ffmpeg
def test_nonpositive_hint_falls_back_to_auto(song_wav):
    """A nonsensical hint (≤0, e.g. from a hand-crafted request) must not blank the grid."""
    wav, _ = song_wav
    auto = analyze_window(wav, 4.0, 12.0)
    for bad in (-120.0, 0.0):
        r = analyze_window(wav, 4.0, 12.0, tempo_hint=bad)
        assert r["analysis"]["beats"] == auto["analysis"]["beats"], "should behave as if no hint"


@needs_ffmpeg
def test_beats_never_reach_the_end_boundary(song_wav):
    """The mask is half-open [start, end): no beat may sit on `end` (next section's downbeat)."""
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0)
    assert all(b < 12.0 for b in r["beats"])


# ---- lock mode: manual authority — the grid is built from the tap, detection bypassed ----

@needs_ffmpeg
def test_lock_builds_a_perfectly_steady_grid(song_wav):
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0, tempo_hint=150.0, lock=True)
    assert r["locked"] is True and r["bpm"] == 150.0
    b = np.array(r["beats"])
    iv = np.diff(b)
    assert len(b) >= 2
    assert iv.std() < 1e-3, "locked grid must be metronomic"
    assert iv.mean() == pytest.approx(60.0 / 150.0, abs=1e-3)
    assert all(4.0 - 1e-6 <= x < 12.0 for x in b)


@needs_ffmpeg
def test_lock_anchors_a_beat_on_the_mark(song_wav):
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0, tempo_hint=120.0, anchor=4.37, beats_per_bar=4, lock=True)
    assert any(abs(b - 4.37) < 1e-3 for b in r["beats"]), "a beat must land exactly on the anchor"
    assert any(abs(d - 4.37) < 1e-3 for d in r["downbeats"]), "the anchor is beat 1 (a downbeat)"


@needs_ffmpeg
def test_lock_tempo_mult_composes(song_wav):
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0, tempo_hint=90.0, tempo_mult=2.0, lock=True)
    assert r["bpm"] == 180.0


@needs_ffmpeg
def test_lock_without_a_tempo_falls_back_to_detect(song_wav):
    """Lock needs a tempo to build from; with none it must not blank the grid."""
    wav, _ = song_wav
    r = analyze_window(wav, 4.0, 12.0, lock=True)   # no hint
    assert r["locked"] is False
    assert r["analysis"]["beats"] > 0
