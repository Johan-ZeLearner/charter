"""The ``Song`` container: metadata + tempo map + per-difficulty notes, and the
one function that writes a complete Clone Hero song folder.

This is the back-half output boundary (Stage 7, docs/02). Nothing downstream of
here writes chart bytes.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .chart_writer import render_chart
from .model import Difficulty, DrumNote
from .songini import SongMeta, render_song_ini
from .tempo import TempoMap


@dataclass
class Song:
    meta: SongMeta
    tempo_map: TempoMap
    tracks: dict[Difficulty, list[DrumNote]] = field(default_factory=dict)
    offset_seconds: float = 0.0

    def render_chart_text(self) -> str:
        sections = {
            diff.chart_section: notes for diff, notes in self.tracks.items() if notes
        }
        return render_chart(
            tempo_map=self.tempo_map,
            tracks=sections,
            name=self.meta.name,
            artist=self.meta.artist,
            charter=self.meta.charter,
            offset_seconds=self.offset_seconds,
        )

    def write_folder(self, folder: str | Path, audio_path: str | Path | None = None) -> Path:
        """Write ``notes.chart`` + ``song.ini`` (+ copied audio) into ``folder``.

        Returns the folder path. ``audio_path`` is copied to ``song<ext>`` if
        given; the MVP symbolic path leaves it out (Phase 5 adds opus encoding).
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "notes.chart").write_text(self.render_chart_text(), encoding="utf-8")
        (folder / "song.ini").write_text(render_song_ini(self.meta), encoding="utf-8")
        if audio_path is not None:
            audio_path = Path(audio_path)
            shutil.copyfile(audio_path, folder / f"song{audio_path.suffix}")
        return folder
