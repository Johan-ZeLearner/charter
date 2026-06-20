"""Tempo map + time signatures, and tick<->seconds conversion.

A single global BPM is the #1 cause of unplayable charts (docs/06), so the
pipeline always carries a full tempo map. ``tick_to_seconds`` integrates over
tempo segments — never assume constant BPM.

Chart tick convention: ``Resolution`` ticks per QUARTER note (docs/03 §2),
universally 192.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DEFAULT_RESOLUTION = 192


@dataclass(frozen=True)
class TempoEvent:
    """A BPM marker. Serialized as ``<tick> = B <round(bpm*1000)>`` (docs/03)."""

    tick: int
    bpm: float

    @property
    def chart_value(self) -> int:
        """BPM * 1000 as an integer, max 3 decimals (the ``B`` value)."""
        return round(self.bpm * 1000)


@dataclass(frozen=True)
class TimeSigEvent:
    """A time signature. ``denominator = 2 ** denom_exp`` (the ``7 4`` gotcha).

    ``TS 7 4`` means 7/16 (2**4), NOT 7/4. Exponent 2 (=/4) is the default and
    is omitted when serialized.
    """

    tick: int
    numerator: int
    denom_exp: int = 2  # 2**2 == 4 -> x/4

    @property
    def denominator(self) -> int:
        return 2**self.denom_exp

    @staticmethod
    def from_fraction(tick: int, numerator: int, denominator: int) -> "TimeSigEvent":
        """Build from a human ``n/d`` (e.g. 7/8), computing the exponent."""
        exp = int(math.log2(denominator))
        if 2**exp != denominator:
            raise ValueError(f"time-signature denominator must be a power of 2: {denominator}")
        return TimeSigEvent(tick=tick, numerator=numerator, denom_exp=exp)


@dataclass
class TempoMap:
    """An ordered tempo + time-signature map for one song.

    Guarantees a tempo marker and a time-signature marker at tick 0 (CH defaults
    to 120 BPM / 4/4 otherwise, but we always emit them explicitly).
    """

    resolution: int = DEFAULT_RESOLUTION
    tempos: list[TempoEvent] = field(default_factory=list)
    time_sigs: list[TimeSigEvent] = field(default_factory=list)

    def normalized(self) -> "TempoMap":
        """Return a copy sorted by tick with tick-0 defaults guaranteed."""
        tempos = sorted(self.tempos, key=lambda e: e.tick)
        sigs = sorted(self.time_sigs, key=lambda e: e.tick)
        if not tempos or tempos[0].tick != 0:
            tempos = [TempoEvent(0, 120.0)] + [t for t in tempos if t.tick != 0]
            tempos.sort(key=lambda e: e.tick)
        if not sigs or sigs[0].tick != 0:
            sigs = [TimeSigEvent(0, 4, 2)] + [s for s in sigs if s.tick != 0]
            sigs.sort(key=lambda e: e.tick)
        return TempoMap(resolution=self.resolution, tempos=tempos, time_sigs=sigs)

    def tick_to_seconds(self, tick: int) -> float:
        """Seconds from chart start to ``tick``, integrating over tempo segments."""
        tempos = self.normalized().tempos
        seconds = 0.0
        for i, ev in enumerate(tempos):
            seg_start = ev.tick
            seg_end = tempos[i + 1].tick if i + 1 < len(tempos) else None
            if tick <= seg_start:
                break
            # seconds per tick at this BPM: (60 / bpm) / resolution
            spt = (60.0 / ev.bpm) / self.resolution
            upper = tick if (seg_end is None or tick < seg_end) else seg_end
            seconds += (upper - seg_start) * spt
            if seg_end is not None and tick <= seg_end:
                break
        return seconds
