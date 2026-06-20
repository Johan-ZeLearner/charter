"""The format firewall: ``DrumNote`` model + ``.chart`` serializer + ``song.ini``.

Every Clone Hero format gotcha (tom/cymbal inversion, opt-in 2x kick, dynamics
encoding, BPM*1000, TS exponent) is isolated to this subpackage (docs/08 §6).
"""

from .chart_writer import render_chart
from .model import Difficulty, DrumNote, Dynamic, Lane
from .song import Song
from .songini import SongMeta, render_song_ini
from .tempo import TempoEvent, TempoMap, TimeSigEvent

__all__ = [
    "Difficulty",
    "DrumNote",
    "Dynamic",
    "Lane",
    "Song",
    "SongMeta",
    "TempoEvent",
    "TempoMap",
    "TimeSigEvent",
    "render_chart",
    "render_song_ini",
]
