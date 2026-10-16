"""DSP baseline: tempo, beat tracking, onset detection on synthetic drums.

The tempo estimator is a hybrid DFT×ACF tempogram (no 120-BPM genre prior). On an
idealised single-pattern synth it may lock any valid *metrical level* (an octave of
the notated tempo) — that ambiguity is inherent and corrected by the studio's
×2/×½ + tap/lock tools. So we assert octave-correctness on ambiguous material and
*exact* tempo only on octave-unambiguous material (an even double-bass run).
"""

from __future__ import annotations

import numpy as np
import pytest

from charter.audio import dsp
from tests.fixtures.synth import (
    synth_drum_track,
    synth_even_kicks,
    synth_tempo_ramp,
)


def _octave_ok(est: float, true: float, tol: float = 0.08) -> bool:
    return any(abs(est - true * m) <= max(8.0, true * m * tol) for m in (0.5, 1.0, 2.0))


@pytest.mark.parametrize("bpm", [100.0, 120.0, 150.0, 180.0])
def test_tempo_estimate_locks_a_metrical_level(bpm):
    """On an ambiguous (hat-on-every-8th) pattern, the estimate is an octave of true."""
    t = synth_drum_track(bpm=bpm, bars=6)
    xp = dsp.hpss_percussive(t.samples, t.sr)
    env, fps = dsp.onset_envelope(xp, t.sr)
    est = dsp.estimate_tempo(env, fps)
    assert _octave_ok(est, bpm), f"estimated {est} is not an octave of {bpm}"


@pytest.mark.parametrize("bpm", [180.0, 200.0, 220.0, 260.0])
def test_fast_double_bass_is_not_halftime(bpm):
    """The core fast-metal guard: an even double-bass run must NOT collapse to ~half.

    This is the bug the old ACF+120-prior (capped at 200 BPM) produced. An even
    kick stream has no half-time subharmonic, so the true fast tempo is unambiguous.
    """
    t = synth_even_kicks(bpm=bpm, count=80)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    est = dsp.estimate_tempo(env, fps)
    assert est > bpm * 0.75, f"estimated {est} for true {bpm} (half-time regression)"
    assert abs(est - bpm) <= bpm * 0.06, f"estimated {est} for true {bpm}"


def test_tempo_can_exceed_old_200_cap():
    """The old estimator hard-capped at bpm_max=200; genuinely fast tempi are now reachable."""
    t = synth_even_kicks(bpm=260.0, count=80)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    assert dsp.estimate_tempo(env, fps) > 200.0


def test_beats_and_interval_consistency():
    t = synth_even_kicks(bpm=120.0, count=32)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    beats = dsp.dp_beat_track(env, fps, dsp.estimate_tempo(env, fps))
    assert 30 <= len(beats) <= 34  # ~32 even kicks
    iois = np.diff(beats / fps)
    assert abs(np.median(iois) - 0.5) < 0.03  # 120 BPM -> 0.5 s


def test_dp_accepts_scalar_and_per_frame_period():
    """Back-compat: a constant per-frame curve must reproduce the scalar fast path EXACTLY."""
    t = synth_even_kicks(bpm=160.0, count=48)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    scalar = dsp.dp_beat_track(env, fps, 160.0)
    arr = dsp.dp_beat_track(env, fps, np.full(len(env), 160.0))
    assert len(scalar) > 0
    assert np.array_equal(scalar, arr), "constant drift curve must equal the scalar path"


def _beat_error(env, fps, frames, truth):
    bt = dsp.refine_beat_frames(env, frames) / fps
    return np.median([np.min(np.abs(bt - tt)) for tt in truth]) if len(bt) else 9.0


def test_drift_dp_beats_a_scalar_period_on_a_steep_ramp():
    """A steep 120→240 accelerando: the per-frame (drift) DP must place beats more
    accurately than a single global period — which over-segments and drifts off here.
    A gentle ramp would pass even with a flat curve, so this uses a ramp steep enough
    that the scalar path genuinely fails (the comparison is what guards the drift code)."""
    t = synth_tempo_ramp(bpm_start=120.0, bpm_end=240.0, beats=120)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    g = dsp.estimate_tempo(env, fps)
    curve = dsp.estimate_tempo_curve(env, fps, center_bpm=g)
    truth = np.array([h[0] for h in t.hits])
    drift = dsp.dp_beat_track(env, fps, curve)
    scalar = dsp.dp_beat_track(env, fps, g)
    e_drift = _beat_error(env, fps, drift, truth)
    e_scalar = _beat_error(env, fps, scalar, truth)
    # drift tracks the ramp accurately...
    assert abs(len(drift) - 120) <= 5 and e_drift < 0.006, f"{len(drift)} beats, {e_drift*1000:.0f} ms"
    # ...and is strictly better than the single-period scalar DP (the whole point)
    assert e_drift < e_scalar
    assert abs(len(drift) - 120) < abs(len(scalar) - 120)


def test_anchored_dp_is_a_hard_pin():
    """A tap / hand-edited beat passed as an anchor must appear exactly in the output."""
    t = synth_even_kicks(bpm=190.0, count=64)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    # an instant deliberately off the kick grid
    anchor = int(round(3.137 * fps))
    frames = dsp.dp_beat_track(env, fps, 190.0, anchors=[anchor])
    assert anchor in set(frames.tolist()), "anchor frame was not pinned as a beat"


def test_tempo_curve_tracks_near_center():
    """The drift curve stays a small deviation around the global estimate (no octave hops)."""
    t = synth_even_kicks(bpm=200.0, count=80)
    env, fps = dsp.onset_envelope(t.samples, t.sr)
    curve = dsp.estimate_tempo_curve(env, fps, center_bpm=200.0)
    assert curve.min() > 200.0 / 1.3 and curve.max() < 200.0 * 1.3


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
