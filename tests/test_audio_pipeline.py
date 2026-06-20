"""End-to-end audio frontend: synthetic drums -> playable, scan-chart-valid folder."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from charter.audio.ingest import ffmpeg_available
from charter.audio.interfaces import AudioBuffer
from charter.audio.pipeline import mp3_to_chart_folder, transcribe_buffer
from charter.audio.separation import PercussiveSeparator
from charter.drumnote.model import Lane

# Pin the dependency-free baseline so the suite is fast and deterministic
# regardless of whether the optional Demucs adapter happens to be installed.
HPSS = PercussiveSeparator()
from charter.validate import assert_four_lane_pro, scan_unavailable_reason
from tests.fixtures.synth import synth_drum_track

needs_scanchart = pytest.mark.skipif(
    scan_unavailable_reason() is not None,
    reason=f"scan-chart unavailable: {scan_unavailable_reason()}",
)
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


def test_transcribe_buffer_produces_notes():
    t = synth_drum_track(bpm=120.0, bars=4)
    song, diag = transcribe_buffer(AudioBuffer(t.samples, t.sr), separator=HPSS)
    notes = song.tracks  # dict
    expert = next(iter(notes.values()))
    assert len(expert) > 0
    assert diag.notes == len(expert)
    assert abs(diag.bpm - 120.0) <= 6.0
    lanes = {n.lane for n in expert}
    assert Lane.KICK in lanes
    assert Lane.RED in lanes  # snare
    assert diag.separator == "hpss"  # baseline (demucs not installed)


@needs_scanchart
def test_buffer_pipeline_validates_as_four_lane_pro(tmp_path):
    from charter.drumnote import Difficulty, Song

    t = synth_drum_track(bpm=120.0, bars=4)
    song, _ = transcribe_buffer(AudioBuffer(t.samples, t.sr), separator=HPSS)
    folder = tmp_path / "song"
    song.write_folder(folder)
    verdict = assert_four_lane_pro(folder)
    assert verdict.ok, f"{verdict.reasons}\n{verdict.report}"
    assert verdict.report["drumTypeName"] == "fourLanePro"


@needs_ffmpeg
@needs_scanchart
def test_file_pipeline_end_to_end_playable(tmp_path):
    """The Phase-3 milestone: an audio file -> a folder Clone Hero will play."""
    t = synth_drum_track(bpm=120.0, bars=6)
    wav = tmp_path / "in.wav"
    wavfile.write(wav, t.sr, (t.samples * 32767).astype(np.int16))

    folder, diag = mp3_to_chart_folder(wav, tmp_path / "song", name="Synth",
                                       artist="charter", separator=HPSS)
    assert (folder / "notes.chart").exists()
    assert (folder / "song.ini").exists()
    assert (folder / "song.opus").exists()  # encoded audio -> actually playable

    verdict = assert_four_lane_pro(folder)
    assert verdict.ok, f"{verdict.reasons}\n{verdict.report}"
    assert verdict.report["drumTypeName"] == "fourLanePro"
    # with audio present, scan-chart should consider it playable
    assert verdict.report["playable"] is True
    assert diag.gate in ("GO", "CAUTION")
