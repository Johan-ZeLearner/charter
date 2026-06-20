"""The audio frontend orchestrator: mp3 -> Song (docs/02 Stages 0-6).

Wires ingest -> separation -> beat/tempo -> transcription -> quantize -> the
Stage-6 mapping + serializer (reused from the symbolic backend). Each ML stage
is a swappable adapter; the baseline runs offline with no model downloads.
"""

from __future__ import annotations

from pathlib import Path

from ..drumnote import Difficulty, Song, SongMeta
from ..mapping import MapConfig, map_events
from .adt import choose_transcriber
from .beats import choose_beat_tracker
from .ingest import decode_audio, encode_opus, read_tags
from .interfaces import AudioBuffer, BeatTracker, Diagnostics, DrumTranscriber, Separator
from .quantize import build_tempo_map, quantize_onsets
from .separation import choose_separator


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

    drums = separator.separate(audio)
    grid = beat_tracker.track(drums)
    onsets = transcriber.transcribe(drums)

    tempo_map = build_tempo_map(grid)
    events = quantize_onsets(onsets, grid, subdivisions=subdivisions)
    mapped = map_events(events, tempo_map, map_config or MapConfig())

    meta = meta or SongMeta()
    if not meta.song_length_ms:
        meta.song_length_ms = int(audio.duration_s * 1000)

    song = Song(
        meta=meta,
        tempo_map=tempo_map,
        tracks={Difficulty.EXPERT: mapped.notes},
    )

    diag = Diagnostics(
        drum_rms=drums.rms(),
        bpm=grid.bpm,
        beats=len(grid.beat_times),
        onsets=len(onsets),
        notes=len(mapped.notes),
        separator=separator.name,
        beat_tracker=beat_tracker.name,
        transcriber=transcriber.name,
        warnings=list(mapped.warnings),
    )
    return song, diag


def transcribe_file(
    path: str | Path,
    *,
    name: str | None = None,
    artist: str | None = None,
    charter: str = "charter AI",
    **kwargs,
) -> tuple[Song, Diagnostics]:
    """Decode a file, read its tags, and run the pipeline."""
    path = Path(path)
    tags = read_tags(path)
    audio = decode_audio(path)
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
    **kwargs,
) -> tuple[Path, Diagnostics]:
    """End-to-end: audio file -> playable Clone Hero song folder (+ song.opus)."""
    song, diag = transcribe_file(path, **kwargs)
    folder = Path(out)
    if encode_audio:
        song.music_stream = "song.opus"  # bind audio in the .chart [Song] block
    song.write_folder(folder)
    if encode_audio:
        encode_opus(path, folder / "song.opus")
    return folder, diag
