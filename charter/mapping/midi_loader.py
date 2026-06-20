"""Load a GM-drum MIDI file into chart-tick events + a tempo map.

Converts MIDI absolute ticks to chart ticks at ``Resolution=192`` and preserves
the MIDI tempo/time-signature map verbatim (no global-BPM assumption, docs/06).

Uses the dependency-free :mod:`charter.mapping.smf` reader. To ingest messy
real-world transcription MIDI later, swap the reader for ``mido`` here; the rest
of the pipeline only sees :class:`RawDrumEvent` + :class:`TempoMap`.
"""

from __future__ import annotations

from pathlib import Path

from ..drumnote.tempo import DEFAULT_RESOLUTION, TempoEvent, TempoMap, TimeSigEvent
from . import smf
from .stage6 import RawDrumEvent

GM_DRUM_CHANNEL = 9  # MIDI channel 10, 0-indexed


def _convert_tick(midi_tick: int, midi_tpq: int, resolution: int) -> int:
    """Scale a MIDI tick onto the chart's ticks-per-quarter grid."""
    return round(midi_tick * resolution / midi_tpq)


def load_drum_midi(
    path: str | Path,
    *,
    resolution: int = DEFAULT_RESOLUTION,
    drum_channel: int | None = GM_DRUM_CHANNEL,
) -> tuple[list[RawDrumEvent], TempoMap]:
    """Read ``path`` and return (drum events in chart ticks, tempo map).

    ``drum_channel=None`` accepts notes on any channel (some transcription tools
    don't set channel 10); by default we filter to the GM drum channel.
    """
    data = read_bytes(path)
    midi = smf.read_midi(data)
    tpq = midi.ticks_per_quarter

    events: list[RawDrumEvent] = []
    for n in midi.note_ons:
        if drum_channel is not None and n.channel != drum_channel:
            continue
        events.append(
            RawDrumEvent(
                tick=_convert_tick(n.tick, tpq, resolution),
                gm_note=n.note,
                velocity=n.velocity,
            )
        )
    events.sort(key=lambda e: (e.tick, e.gm_note))

    tempos = [
        TempoEvent(_convert_tick(t.tick, tpq, resolution), t.bpm) for t in midi.tempos
    ]
    time_sigs = [
        TimeSigEvent(_convert_tick(s.tick, tpq, resolution), s.numerator, s.denom_exp)
        for s in midi.time_sigs
    ]
    tempo_map = TempoMap(
        resolution=resolution, tempos=tempos, time_sigs=time_sigs
    ).normalized()

    return events, tempo_map


def read_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()
