"""Unit tests for the ``.chart`` serializer — the format firewall.

These pin the exact note numbers so the tom/cymbal inversion, dynamics, 2x kick,
BPM*1000, and the TS exponent can never silently regress.
"""

from __future__ import annotations

import pytest

from charter.drumnote import DrumNote, Dynamic, Lane, TempoMap
from charter.drumnote.chart_writer import (
    render_chart,
    render_difficulty_section,
    render_sync_track,
)
from charter.drumnote.tempo import TempoEvent, TimeSigEvent


def _lines(section: str) -> set[str]:
    return {ln.strip() for ln in section.splitlines() if "=" in ln and "N " in ln}


def test_cymbal_inversion_yellow_cymbal_emits_flag_66():
    section = render_difficulty_section(
        "ExpertDrums", [DrumNote(384, Lane.YELLOW, is_cymbal=True)]
    )
    lines = _lines(section)
    assert "384 = N 2 0" in lines  # yellow gem
    assert "384 = N 66 0" in lines  # opt-in cymbal flag


def test_blue_tom_is_default_no_flag():
    section = render_difficulty_section("ExpertDrums", [DrumNote(0, Lane.BLUE)])
    lines = _lines(section)
    assert "0 = N 3 0" in lines
    assert not any("N 67" in ln for ln in lines)  # no cymbal flag => tom


def test_green_cymbal_emits_flag_68():
    section = render_difficulty_section(
        "ExpertDrums", [DrumNote(0, Lane.GREEN, is_cymbal=True)]
    )
    lines = _lines(section)
    assert "0 = N 4 0" in lines
    assert "0 = N 68 0" in lines


def test_red_accent_and_blue_ghost_flags():
    section = render_difficulty_section(
        "ExpertDrums",
        [
            DrumNote(0, Lane.RED, dynamic=Dynamic.ACCENT),
            DrumNote(0, Lane.BLUE, dynamic=Dynamic.GHOST),
        ],
    )
    lines = _lines(section)
    assert "0 = N 1 0" in lines  # red gem (always tom)
    assert "0 = N 34 0" in lines  # red accent
    assert "0 = N 3 0" in lines  # blue gem
    assert "0 = N 42 0" in lines  # blue ghost


def test_kick_and_2x_kick():
    section = render_difficulty_section(
        "ExpertDrums",
        [DrumNote(0, Lane.KICK), DrumNote(48, Lane.KICK, is_kick2x=True)],
    )
    lines = _lines(section)
    assert "0 = N 0 0" in lines  # normal kick
    assert "48 = N 32 0" in lines  # double-kick is opt-in type 32


def test_synctrack_bpm_times_1000_and_ts_exponent():
    tm = TempoMap(
        tempos=[TempoEvent(0, 150.5)],
        time_sigs=[TimeSigEvent.from_fraction(0, 7, 8)],
    )
    out = render_sync_track(tm)
    assert "0 = B 150500" in out  # 150.5 BPM -> 150500
    assert "0 = TS 7 3" in out  # 7/8 -> exponent 3 (2**3 == 8)


def test_synctrack_omits_exponent_for_quarter_denominator():
    tm = TempoMap(tempos=[TempoEvent(0, 120.0)], time_sigs=[TimeSigEvent(0, 4, 2)])
    out = render_sync_track(tm)
    assert "0 = TS 4" in out
    assert "TS 4 2" not in out  # /4 exponent is omitted


def test_render_chart_has_song_header_and_resolution():
    tm = TempoMap()
    text = render_chart(
        tempo_map=tm,
        tracks={"ExpertDrums": [DrumNote(0, Lane.KICK)]},
        name="X",
        artist="Y",
        charter="Z",
    )
    assert "[Song]" in text
    assert "Resolution = 192" in text
    assert "[ExpertDrums]" in text


def test_model_rejects_illegal_notes():
    with pytest.raises(ValueError):
        DrumNote(0, Lane.RED, is_cymbal=True)  # red can never be a cymbal
    with pytest.raises(ValueError):
        DrumNote(0, Lane.YELLOW, is_kick2x=True)  # only kick can be 2x
    with pytest.raises(ValueError):
        DrumNote(-1, Lane.KICK)  # negative tick
