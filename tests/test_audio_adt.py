"""Baseline ADT classifier accuracy on synthetic drums."""

from __future__ import annotations

from charter.audio.adt import GM_CLOSED_HAT, GM_KICK, GM_SNARE, BaselineDrumTranscriber
from charter.audio.interfaces import AudioBuffer
from tests.fixtures.synth import synth_drum_track

_GM_TO_LABEL = {GM_KICK: "kick", GM_SNARE: "snare", GM_CLOSED_HAT: "hat"}


def _eval(bpm=120.0, bars=4, tol=0.04):
    t = synth_drum_track(bpm=bpm, bars=bars)
    preds = BaselineDrumTranscriber().transcribe(AudioBuffer(t.samples, t.sr))
    pred_pairs = [(p.time_s, _GM_TO_LABEL[p.gm_note]) for p in preds]

    # recall: each truth hit has a predicted (label) within tol
    matched = 0
    for (tt, lab) in t.hits:
        if any(abs(pt - tt) <= tol and pl == lab for pt, pl in pred_pairs):
            matched += 1
    recall = matched / len(t.hits)

    # precision: each prediction matches some truth hit
    good = 0
    for pt, pl in pred_pairs:
        if any(abs(pt - tt) <= tol and pl == lab for tt, lab in t.hits):
            good += 1
    precision = good / max(1, len(pred_pairs))
    return precision, recall, pred_pairs


def test_classifier_precision_recall():
    precision, recall, _ = _eval()
    assert precision >= 0.85, f"precision {precision:.2f}"
    assert recall >= 0.70, f"recall {recall:.2f}"


def test_kicks_and_hats_present():
    _, _, preds = _eval()
    labels = {lab for _, lab in preds}
    assert "kick" in labels
    assert "hat" in labels
    assert "snare" in labels
