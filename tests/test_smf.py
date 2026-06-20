"""Round-trip tests for the dependency-free SMF reader/writer."""

from __future__ import annotations

from charter.mapping import smf
from charter.mapping.smf import DrumHit, SetTempo, TimeSignature


def test_write_read_roundtrip_notes():
    hits = [
        DrumHit(0, 36, 100),
        DrumHit(240, 38, 30),
        DrumHit(480, 42, 127),
        # a large tick to exercise multi-byte variable-length quantities
        DrumHit(100_000, 49, 90),
    ]
    data = smf.write_drum_midi(ticks_per_quarter=480, hits=hits)
    midi = smf.read_midi(data)

    assert midi.ticks_per_quarter == 480
    got = sorted((n.tick, n.note, n.velocity, n.channel) for n in midi.note_ons)
    assert got == [
        (0, 36, 100, 9),
        (240, 38, 30, 9),
        (480, 42, 127, 9),
        (100_000, 49, 90, 9),
    ]


def test_write_read_roundtrip_tempo_and_timesig():
    data = smf.write_drum_midi(
        ticks_per_quarter=480,
        hits=[DrumHit(0, 36, 100)],
        tempos=[SetTempo(0, 500_000), SetTempo(1920, round(60_000_000 / 180))],
        time_sigs=[TimeSignature(0, 4, 2), TimeSignature(1920, 7, 3)],
    )
    midi = smf.read_midi(data)

    bpms = sorted((t.tick, round(t.bpm)) for t in midi.tempos)
    assert bpms == [(0, 120), (1920, 180)]
    sigs = sorted((s.tick, s.numerator, s.denom_exp) for s in midi.time_sigs)
    assert sigs == [(0, 4, 2), (1920, 7, 3)]


def test_smpte_division_rejected():
    # 0x8000 high bit set => SMPTE timing, unsupported by CH.
    bad = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + (0xE728).to_bytes(2, "big")
    try:
        smf.read_midi(bad)
    except ValueError as e:
        assert "SMPTE" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for SMPTE division")
