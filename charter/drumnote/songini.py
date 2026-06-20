"""``song.ini`` writer (docs/03 §8, docs/07 §9).

We always write ``pro_drums=True`` so drum-type detection never relies on
heuristics, and ``five_lane_drums=False``. Sync is baked into the chart's
``Offset`` — we deliberately do NOT write ``delay`` (it breaks leaderboard-hash
parity).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SongMeta:
    name: str = "Untitled"
    artist: str = "Unknown Artist"
    album: str = "Unknown Album"
    genre: str = "Unknown"
    year: str = ""
    charter: str = "charter AI"
    # 0..6 intensity (metadata only), or -1 if the track is absent.
    diff_drums: int = 0
    song_length_ms: int = 0
    preview_start_ms: int = 0


def render_song_ini(meta: SongMeta) -> str:
    """Render ``song.ini`` with the drum-critical flags set for 4-lane Pro."""
    lines = [
        "[Song]",
        f"name = {meta.name}",
        f"artist = {meta.artist}",
        f"album = {meta.album}",
        f"genre = {meta.genre}",
        f"year = {meta.year}",
        f"charter = {meta.charter}",
        f"diff_drums = {meta.diff_drums}",
        # Force the drums track to parse as 4-lane Pro; never set both flags.
        "pro_drums = True",
        "five_lane_drums = False",
        f"song_length = {meta.song_length_ms}",
        f"preview_start_time = {meta.preview_start_ms}",
        # NOTE: no `delay` — offset is baked into the .chart [Song] Offset.
    ]
    return "\n".join(lines) + "\n"
