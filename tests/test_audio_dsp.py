"""DSP baseline: tempo, beat tracking, onset detection on synthetic drums."""

from __future__ import annotations

import numpy as np
import pytest

from charter.audio import dsp
from tests.fixtures.synth import synth_drum_track


@pytest.mark.parametrize("bpm", [100.0, 120.0, 150.0])
def test_tempo_estimate_close(bpm):
    t = synth_drum_track(bpm=bpm, bars=4)
    xp = dsp.hpss_percussive(t.samples, t.sr)
    env, fps = dsp.onset_envelope(xp, t.sr)
    est = dsp.estimate_tempo(env, fps)
    assert abs(est - bpm) <= 6.0, f"estimated {est} for true {bpm}"


def test_beats_and_interval_consistency():
    t = synth_drum_track(bpm=120.0, bars=4)
    xp = dsp.hpss_percussive(t.samples, t.sr)
    env, fps = dsp.onset_envelope(xp, t.sr)
    beats = dsp.dp_beat_track(env, fps, dsp.estimate_tempo(env, fps))
    assert 14 <= len(beats) <= 18  # ~16 over 4 bars
    iois = np.diff(beats / fps)
    assert abs(np.median(iois) - 0.5) < 0.03  # 120 BPM -> 0.5s


def test_onsets_detected():
    t = synth_drum_track(bpm=120.0, bars=2)
    xp = dsp.hpss_percussive(t.samples, t.sr)
    env, fps = dsp.onset_envelope(xp, t.sr)
    onsets = dsp.peak_pick(env, fps)
    # 2 bars: 8 beats, hat on every 8th (16) with kick/snare coincident -> ~16 onsets
    assert 12 <= len(onsets) <= 20


def test_silence_has_no_beats_or_onsets():
    env, fps = dsp.onset_envelope(np.zeros(44100, dtype=np.float32), 44100)
    assert len(dsp.peak_pick(env, fps)) == 0
