"""The audio frontend orchestrator: mp3 -> Song (docs/02 Stages 0-6).

Wires ingest -> separation -> beat/tempo -> transcription -> quantize -> the
Stage-6 mapping + serializer (reused from the symbolic backend). Each ML stage
is a swappable adapter; the baseline runs offline with no model downloads.

Emits ``charter.audio`` INFO logs per stage (with timing) so a long run shows
progress. The CLI turns these on; library callers stay quiet unless they
configure logging.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path

from ..drumnote import Difficulty, Song, SongMeta
from ..mapping import MapConfig, map_events
from .adt import choose_transcriber
from .beats import choose_beat_tracker
from .ingest import decode_audio, encode_opus, read_tags
from .interfaces import AudioBuffer, BeatTracker, Diagnostics, DrumTranscriber, Separator
from .quantize import build_tempo_map, quantize_onsets
from .separation import choose_separator

log = logging.getLogger("charter.audio")


@contextmanager
def _stage(name: str):
    log.info("→ %s ...", name)
    t0 = time.perf_counter()
    yield
    log.info("  ✓ %s (%.1fs)", name, time.perf_counter() - t0)


def transcribe_buffer(
    audio: AudioBuffer,
    *,
    meta: SongMeta | None = None,
    separator: Separator | None = None,
    beat_tracker: BeatTracker | None = None,
    transcriber: DrumTranscriber | None = None,
    map_config: MapConfig | None = None,
    subdivisions: int = 4,
) -> tuple[Song, Diagnostics]:
    """Run the full audio->Song pipeline on an in-memory mono buffer (no I/O)."""
    separator = separator or choose_separator()
    beat_tracker = beat_tracker or choose_beat_tracker()
    transcriber = transcriber or choose_transcriber()
    log.info(
        "pipeline: %.1fs audio | sep=%s beats=%s adt=%s",
        audio.duration_s, separator.name, beat_tracker.name, transcriber.name,
    )

    with _stage(f"Stage 1 separation [{separator.name}]"):
        drums = separator.separate(audio)
    # Beat tracking always wants a percussive signal. A self-separating
    # transcriber (e.g. drumsep) pairs with a passthrough separator, so `drums`
    # is the raw mix there — emphasize percussion via HPSS just for the grid.
    with _stage(f"Stage 3 beat/tempo [{beat_tracker.name}]"):
        if separator.name == "passthrough":
            from . import dsp
            beat_sig = AudioBuffer(dsp.hpss_percussive(audio.samples, audio.sr), audio.sr)
        else:
            beat_sig = drums
        grid = beat_tracker.track(beat_sig)
    log.info("    ~%.1f BPM, %d beats", grid.bpm, len(grid.beat_times))
    with _stage(f"Stage 4 transcription [{transcriber.name}]"):
        onsets = transcriber.transcribe(drums)
    log.info("    %d onsets", len(onsets))
    with _stage("Stage 5-6 quantize + GM->CH map"):
        tempo_map = build_tempo_map(grid)
        events = quantize_onsets(onsets, grid, subdivisions=subdivisions)
        mapped = map_events(events, tempo_map, map_config or MapConfig())
    log.info("    %d notes", len(mapped.notes))

    meta = meta or SongMeta()
    if not meta.song_length_ms:
        meta.song_length_ms = int(audio.duration_s * 1000)

    song = Song(meta=meta, tempo_map=tempo_map, tracks={Difficulty.EXPERT: mapped.notes})
    diag = Diagnostics(
        drum_rms=drums.rms(), bpm=grid.bpm, beats=len(grid.beat_times),
        onsets=len(onsets), notes=len(mapped.notes), separator=separator.name,
        beat_tracker=beat_tracker.name, transcriber=transcriber.name,
        warnings=list(mapped.warnings),
    )
    return song, diag


def transcribe_file(
    path: str | Path,
    *,
    name: str | None = None,
    artist: str | None = None,
    charter: str = "charter AI",
    max_seconds: float | None = None,
    **kwargs,
) -> tuple[Song, Diagnostics]:
    """Decode a file, read its tags, and run the pipeline."""
    path = Path(path)
    tags = read_tags(path)
    with _stage(f"Stage 0 decode/normalize{' (clip %ss)' % max_seconds if max_seconds else ''}"):
        audio = decode_audio(path, max_seconds=max_seconds)
    meta = SongMeta(
        name=name or tags.title or path.stem,
        artist=artist or tags.artist or "Unknown Artist",
        album=tags.album or "Unknown Album",
        year=tags.year or "",
        charter=charter,
        song_length_ms=tags.duration_ms,
    )
    return transcribe_buffer(audio, meta=meta, **kwargs)


def mp3_to_chart_folder(
    path: str | Path,
    out: str | Path,
    *,
    encode_audio: bool = True,
    max_seconds: float | None = None,
    **kwargs,
) -> tuple[Path, Diagnostics]:
    """End-to-end: audio file -> playable Clone Hero song folder (+ song.opus)."""
    song, diag = transcribe_file(path, max_seconds=max_seconds, **kwargs)
    folder = Path(out)
    if encode_audio:
        song.music_stream = "song.opus"  # bind audio in the .chart [Song] block
    with _stage("Stage 7 write .chart + song.ini"):
        song.write_folder(folder)
    if encode_audio:
        with _stage("Stage 7 encode song.opus"):
            encode_opus(path, folder / "song.opus", max_seconds=max_seconds)
    return folder, diag
