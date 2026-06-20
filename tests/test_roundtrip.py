"""End-to-end round-trip: hand-made GM MIDI -> .chart -> scan-chart.

The scan-chart integration is skipped automatically if Node/scan-chart isn't
available, so the pure-Python suite always runs. The Phase-1 milestone is the
``test_basic_groove_*`` assertions: Clone Hero's own parser detects 4-lane Pro.
"""

from __future__ import annotations

import pytest

from charter.drumnote import Difficulty, Song, SongMeta
from charter.drumnote.model import Lane
from charter.mapping import load_drum_midi, map_events
from charter.validate import assert_four_lane_pro, scan_unavailable_reason
from tests.fixtures import make_fixtures

scanchart = pytest.mark.skipif(
    scan_unavailable_reason() is not None,
    reason=f"scan-chart unavailable: {scan_unavailable_reason()}",
)


def _build_song_folder(midi_bytes: bytes, tmp_path) -> str:
    mid = tmp_path / "in.mid"
    mid.write_bytes(midi_bytes)
    events, tempo_map = load_drum_midi(mid)
    result = map_events(events, tempo_map)
    song = Song(
        meta=SongMeta(name="Fixture", artist="charter tests"),
        tempo_map=tempo_map,
        tracks={Difficulty.EXPERT: result.notes},
    )
    folder = tmp_path / "song"
    song.write_folder(folder)
    return str(folder)


def test_tempo_change_chart_has_correct_synctrack(tmp_path):
    """Unit-level: 180 BPM marker and the 7/8 time signature survive into the chart."""
    mid = tmp_path / "tc.mid"
    mid.write_bytes(make_fixtures.build_tempo_change())
    events, tempo_map = load_drum_midi(mid)
    song = Song(
        meta=SongMeta(),
        tempo_map=tempo_map,
        tracks={Difficulty.EXPERT: map_events(events, tempo_map).notes},
    )
    text = song.render_chart_text()
    assert "B 120000" in text
    assert "B 180000" in text
    assert "TS 7 3" in text  # 7/8 via exponent, not "TS 7 8"


def test_basic_groove_maps_expected_lanes(tmp_path):
    """Unit-level: the groove produces kick/red/yellow-cymbal/tom gems."""
    mid = tmp_path / "bg.mid"
    mid.write_bytes(make_fixtures.build_basic_groove())
    events, tempo_map = load_drum_midi(mid)
    notes = map_events(events, tempo_map).notes
    lanes = {(n.lane, n.is_cymbal) for n in notes}
    assert (Lane.KICK, False) in lanes
    assert (Lane.RED, False) in lanes
    assert (Lane.YELLOW, True) in lanes  # hi-hats
    assert (Lane.BLUE, True) in lanes  # crash
    assert any(n.lane in (Lane.YELLOW, Lane.BLUE, Lane.GREEN) and not n.is_cymbal for n in notes)  # tom fill


@scanchart
def test_basic_groove_scanchart_detects_four_lane_pro(tmp_path):
    folder = _build_song_folder(make_fixtures.build_basic_groove(), tmp_path)
    verdict = assert_four_lane_pro(folder)
    assert verdict.ok, f"scan-chart rejected the chart: {verdict.reasons}\n{verdict.report}"
    assert verdict.report["drumTypeName"] == "fourLanePro"
    assert "drums" in verdict.report["instruments"]


@scanchart
def test_double_kick_scanchart_reports_2x(tmp_path):
    folder = _build_song_folder(make_fixtures.build_double_kick(), tmp_path)
    verdict = assert_four_lane_pro(folder)
    assert verdict.ok, f"{verdict.reasons}\n{verdict.report}"
    assert verdict.report["has2xKick"] is True


@scanchart
def test_tempo_change_scanchart_passes(tmp_path):
    folder = _build_song_folder(make_fixtures.build_tempo_change(), tmp_path)
    verdict = assert_four_lane_pro(folder)
    assert verdict.ok, f"{verdict.reasons}\n{verdict.report}"
